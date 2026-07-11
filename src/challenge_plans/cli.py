"""CLI entrypoint: `challenge-plans run | weigh | doctor`.

`run`    — adversarial review of an artifact (spec/diff); 6-state verdict + surviving objections.
`weigh`  — deliberation: multiple agents vote across options; ranked recommendation + dissent.
`doctor` — report which backend CLIs (claude/codex) are logged in and usable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .adapters import ClaudeAdapter, CodexAdapter, ProbeState, discover_byo_adapters
from .deliberation import weigh_options
from .engine import run_challenge

_ALL_ADAPTERS = [ClaudeAdapter, CodexAdapter]


def _discover_adapters() -> list:
    """Cheap run-time discovery of usable adapters (claude if installed; codex if logged in)."""
    # Instantiate each adapter once: the probe in available() (e.g. codex's `login status`
    # subprocess) must run on the same instance we keep, not a throwaway.
    discovered = []
    for cls in _ALL_ADAPTERS:
        adapter = cls()
        if adapter.available():
            discovered.append(adapter)
    byo, problems = discover_byo_adapters()
    for p in problems:  # a silently skipped half-configured backend is a footgun — say so
        print(f"warning: {p}", file=sys.stderr)
    discovered.extend(a for a in byo if a.available())
    return discovered


# Default is advisory (does not block CI). Only --enforce maps
# request_changes/inconclusive/schema_invalid to a non-zero exit.
_ENFORCE_EXIT = {
    "approve": 0, "approve_with_unverified_timeouts": 0, "discuss": 0,
    "request_changes": 1, "inconclusive": 1, "schema_invalid": 2,
}
# --strict is a hard gate: only a clean approve passes. discuss (e.g. a single-family run capped
# at discuss) and approve_with_unverified_timeouts now fail, so a gate can't look passed while
# nothing was actually cross-verified.
_STRICT_EXIT = {
    "approve": 0,
    "approve_with_unverified_timeouts": 1, "discuss": 1,
    "request_changes": 1, "inconclusive": 1, "schema_invalid": 2,
}


def _exit_code(verdict: str, enforce: bool, strict: bool = False) -> int:
    if strict:
        return _STRICT_EXIT.get(verdict, 1)
    if not enforce:
        return 0  # advisory: the verdict is informational, it does not break CI
    return _ENFORCE_EXIT.get(verdict, 1)


def _utcnow():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc)


def _save_provenance(manifest: dict, save_dir: str) -> str:
    """Persist a run record (tool version + UTC timestamp + full manifest) for audit/replay."""
    import os
    import pathlib
    d = pathlib.Path(save_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    ts = _utcnow()
    record = {"tool": "challenge-plans", "tool_version": __version__,
              "created_at": ts.isoformat(), "manifest": manifest}
    stem = f"run-{ts:%Y%m%dT%H%M%S_%fZ}-{manifest.get('artifact_hash', 'na')}"
    path, n = d / f"{stem}.json", 1
    while path.exists():  # an audit record must never silently overwrite an earlier one
        path, n = d / f"{stem}-{n}.json", n + 1
    # Atomic: write to a temp file then rename, so a crash mid-write can't leave a partial record.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def _render_markdown(m: dict) -> str:
    pi = m["panel_integrity"]
    div = m["source_diversity"]
    lines = [f"# challenge-plans · {m['mode']} · verdict: **{m['verdict']}**",
             f"- artifact: `{m['artifact_hash']}` ({m['artifact_type']}, profile={m['profile']})",
             f"- panel: expected {pi['expected_voters']} / collected {pi['collected_voters']}"
             + (f" · ⚠️missing {pi['missing']}" if pi["missing"] else " · complete ✓"),
             f"- diversity: {div['families']} families"
             + (f" · ⚠️{div['warning']}" if div.get("warning") else ""),
             f"- cross-family confirmed: {len(m.get('verifications', []))} high/critical reviewed"
             + " (✓ = another model family reproduced it with a line anchor — not a mechanical test;"
             + " may hard-gate · ? = unconfirmed, advisory)",
             f"- surviving objections: {len([c for c in m['concerns'] if c['status'] != 'rebutted'])}"
             + (f" · dropped {len(m['dropped_concerns'])}" if m.get("dropped_concerns") else "")
             + (f" · rebutted {len([c for c in m['concerns'] if c['status']=='rebutted'])}"
                if any(c['status'] == 'rebutted' for c in m['concerns']) else ""), ""]
    pcs = m.get("project_checks", [])
    if pcs:
        failed = [c for c in pcs if c["status"] == "failed"]
        advisory = [c for c in pcs if c["status"] in ("errored", "timed_out")]
        lines.insert(len(lines) - 1,
                     f"- project checks: {len(pcs)} mechanical (your own commands, not an LLM)"
                     + (f" · ❌ {len(failed)} failed → hard-gates" if failed else " · all passed ✓")
                     + (f" · ⚠️{len(advisory)} errored/timed-out (advisory)" if advisory else ""))
        for c in failed:
            lines.insert(len(lines) - 1, f"  - failed: `{c['cmd']}` (exit {c['exit_code']})")
    for c in m["concerns"]:
        if c["status"] == "rebutted":
            continue
        # A ✓ minted through a user-declared (BYO) family is asserted independence, not the
        # builtin cross-family guarantee — it must render visibly different.
        mark = "?"
        if c.get("severity_verified"):
            mark = ("✓" if c.get("verified_family_source", "builtin") != "user_declared"
                    else "✓(user-declared family)")
        lines.append(f"- [{c['severity']}{mark}] {c['title']} `@{c['artifact_span']}` "
                     f"({c['failure_type']}, by {','.join(c['raised_by'])})")
    return "\n".join(lines)


def _apply_lang(args: argparse.Namespace) -> None:
    # Single English-source codebase, localized output: --lang sets the env var the prompt
    # builders read. Default "en" leaves prompts untouched.
    if getattr(args, "lang", None):
        os.environ["CHALLENGE_PLANS_LANG"] = args.lang


def _cmd_run(args: argparse.Namespace) -> int:
    _apply_lang(args)
    if args.mode != "challenge":
        print("Deliberation runs via the `weigh` subcommand; `run --mode council` is reserved.",
              file=sys.stderr)
        return 2
    try:
        manifest = run_challenge(
            args.artifact, args.type, args.profile, _discover_adapters(),
            verify_cmds=getattr(args, "verify", None),
            record_backends=bool(getattr(args, "save", None)))
    except NotImplementedError as e:
        print(str(e), file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print("Artifact is not UTF-8 — convert it to UTF-8 and retry "
              "(e.g. a file copied from GBK/Windows).", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Failed to read artifact: {e}", file=sys.stderr)
        return 2

    if args.sink == "markdown":
        print(_render_markdown(manifest))
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if getattr(args, "save", None):
        # stderr so it never pollutes a piped --sink stdout JSON. A save I/O error must not crash
        # the run or discard the gate exit code — provenance is a side effect, not the verdict.
        try:
            print(f"saved provenance: {_save_provenance(manifest, args.save)}", file=sys.stderr)
        except OSError as e:
            print(f"warning: could not save provenance to {args.save}: {e}", file=sys.stderr)
    return _exit_code(manifest["verdict"], args.enforce, getattr(args, "strict", False))


def _render_deliberation(m: dict) -> str:
    div = m["source_diversity"]
    lines = [f"# weigh-options · deliberation · recommendation: **{m['recommendation']}**",
             f"- question: {m['question']}",
             f"- diversity: {div['families']} families · {m['panel_integrity']['collected_voters']} votes collected"
             + (f" · ⚠️{div['warning']}" if div.get("warning") else ""),
             "- ranking (weighted Borda; raw = first-choice votes, weighted = after family cap):"]
    for o in sorted(m["options"], key=lambda x: x["rank"]):
        flag = " ⚠️unverified blocker claim" if o["blocked"] else ""
        lines.append(f"  {o['rank']}. [{o['id']}] raw={o['raw_first_choice']} "
                     f"weighted={o['weighted_score']}{flag} — {o['text'][:40]}")
    if m.get("raw_weighted_conflict"):
        lines.append(f"- ⚠️ raw majority ([{m['raw_winner']}]) ≠ weighted winner ([{m['weighted_winner']}]): "
                     "the family cap is doing its job — **don't read this as an N:1 landslide**")
    if m.get("strongest_dissent"):
        d = m["strongest_dissent"]
        lines.append(f"- strongest dissent: {d['by']} prefers [{d['prefers']}]: {d['reason']}")
    if m.get("winner_unverified_blocker"):
        b = m["winner_unverified_blocker"][0]
        lines.append(f"- ⚠️ weighted winner has an unverified blocker claim: {b['blocker']} "
                     "→ verify it in challenge mode before deciding")
    if m["recommendation"] == "discuss":
        lines.append("- ⚖️ single family / weighted tie / contested winner → hand to owner (tie_breaker=owner)")
    return "\n".join(lines)


def _cmd_weigh(args: argparse.Namespace) -> int:
    _apply_lang(args)
    import yaml
    try:
        with open(args.options_file, encoding="utf-8") as f:
            spec = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError) as e:
        print(f"Failed to read options file: {e}", file=sys.stderr)
        return 2
    except yaml.YAMLError as e:
        print(f"Options file is not valid YAML/JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(spec, dict) or not spec.get("question") or not spec.get("options"):
        print("Options file must contain `question` and `options: [{id, text}]` (≥2 options).",
              file=sys.stderr)
        return 2
    try:
        m = weigh_options(spec["question"], spec["options"], _discover_adapters(), args.profile)
    except (RuntimeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.sink == "markdown":
        print(_render_deliberation(m))
    else:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    # recommendation is an option id → 0; discuss/inconclusive exit non-zero under --enforce
    decided = m["recommendation"] not in ("discuss", "inconclusive")
    return 0 if (decided or not args.enforce) else 1


def _remediation(adapter, state: ProbeState) -> str:
    """Actionable next step for a non-ready backend, so humans and agents know how to fix it."""
    if state == ProbeState.NOT_INSTALLED:
        return getattr(adapter, "install_hint", "")
    if state == ProbeState.NOT_LOGGED_IN:
        return getattr(adapter, "login_hint", "")
    if state == ProbeState.BILLING_UNKNOWN:
        return "logged in but returned no usable output — check the subscription is active / not rate-limited"
    if state == ProbeState.INTERACTIVE_ONLY:
        return "only runs interactively here; not usable for non-interactive review"
    if state == ProbeState.UNSUPPORTED_VERSION:
        return getattr(adapter, "update_hint", "update this CLI to a supported version")
    return ""


def _cmd_doctor(args: argparse.Namespace) -> int:
    any_ready = False
    byo, problems = discover_byo_adapters()
    for a in [cls() for cls in _ALL_ADAPTERS] + byo:
        state = a.probe()
        any_ready = any_ready or state == ProbeState.READY
        declared = ", user-declared family" if a.family_source == "user_declared" else ""
        line = f"{a.backend} ({a.model_family}{declared}): {state.value}"
        if state != ProbeState.READY:
            hint = _remediation(a, state)
            if hint:
                line += f"  → {hint}"
        print(line)
    for p in problems:
        print(f"misconfigured: {p}")
    if not any_ready:
        print("\nNo usable backend. challenge-plans drives a logged-in subscription CLI "
              "(no API keys) — it cannot run without at least one.")
        print("  • Have a Claude or ChatGPT subscription? Install / log into the matching CLI above.")
        print("  • Don't have one yet? You'll need a subscription to one of them to run this tool.")
    return 0 if any_ready else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="challenge-plans",
        description="Multi-agent adversarial hardening of plans/specs on subscription CLIs "
                    "(reduce rework before execution).",
    )
    p.add_argument("--version", action="version", version=f"challenge-plans {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="adversarially review an artifact (spec/diff)")
    run.add_argument("artifact", help="path to the artifact to review (spec/plan/diff/adr)")
    run.add_argument("--type", choices=["spec", "plan", "diff", "decision"],
                     default="spec", help="artifact type (selects the rubric / failure_type set)")
    run.add_argument("--mode", choices=["challenge", "council"], default="challenge",
                     help="challenge (adversarial); council reserved — deliberation runs via `weigh`")
    run.add_argument("--profile", choices=["fast", "standard", "deep"], default="standard",
                     help="panel size / depth")
    run.add_argument("--sink", choices=["stdout", "markdown"],
                     default="stdout", help="output format (github-pr-comment pending)")
    run.add_argument("--enforce", action="store_true",
                     help="CI gate: request_changes/inconclusive/schema_invalid exit non-zero; "
                          "discuss/approve exit 0. Advisory (exit 0) without it")
    run.add_argument("--strict", action="store_true",
                     help="hard gate: only a clean `approve` passes; discuss / "
                          "approve_with_unverified_timeouts also exit non-zero")
    run.add_argument("--verify", action="append", metavar="CMD",
                     help="run a mechanical check — your own command, e.g. \"pytest -q\" — in the "
                          "current directory; a failed check sets the verdict to request_changes. "
                          "Repeatable. The command runs as-is and is NEVER derived from the "
                          "artifact; combine with --enforce/--strict to break CI")
    run.add_argument("--save", metavar="DIR",
                     help="persist a run record (tool version + timestamp + full manifest) to DIR "
                          "for audit / replay")
    run.add_argument("--lang", default="en", metavar="LANG",
                     help="language for human-readable output (e.g. en, zh, ja); "
                          "JSON keys / enums / line anchors stay stable. Default en")
    run.set_defaults(func=_cmd_run)

    weigh = sub.add_parser("weigh", help="deliberation: multiple agents vote across options (weigh-options)")
    weigh.add_argument("options_file", help="YAML/JSON file: {question, options: [{id, text}]}")
    weigh.add_argument("--profile", choices=["fast", "standard", "deep"], default="standard")
    weigh.add_argument("--sink", choices=["stdout", "markdown"], default="stdout")
    weigh.add_argument("--enforce", action="store_true",
                       help="exit non-zero when recommendation is discuss/inconclusive; 0 by default")
    weigh.add_argument("--lang", default="en", metavar="LANG",
                       help="language for human-readable output (e.g. en, zh, ja); "
                            "JSON keys / enums stay stable. Default en")
    weigh.set_defaults(func=_cmd_weigh)

    doctor = sub.add_parser("doctor", help="check which backend CLIs are logged in / usable")
    doctor.set_defaults(func=_cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
