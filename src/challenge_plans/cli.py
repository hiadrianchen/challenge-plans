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
from .adapters import ClaudeAdapter, CodexAdapter, ProbeState
from .deliberation import weigh_options
from .engine import run_challenge

_ALL_ADAPTERS = [ClaudeAdapter, CodexAdapter]


def _discover_adapters() -> list:
    """Cheap run-time discovery of usable adapters (claude if installed; codex if logged in)."""
    return [a() for a in _ALL_ADAPTERS if a().available()]


# Default is advisory (does not block CI). Only --enforce maps
# request_changes/inconclusive/schema_invalid to a non-zero exit.
_ENFORCE_EXIT = {
    "approve": 0, "approve_with_unverified_timeouts": 0, "discuss": 0,
    "request_changes": 1, "inconclusive": 1, "schema_invalid": 2,
}


def _exit_code(verdict: str, enforce: bool) -> int:
    if not enforce:
        return 0  # advisory: the verdict is informational, it does not break CI
    return _ENFORCE_EXIT.get(verdict, 1)


def _render_markdown(m: dict) -> str:
    pi = m["panel_integrity"]
    div = m["source_diversity"]
    lines = [f"# challenge-plans · {m['mode']} · verdict: **{m['verdict']}**",
             f"- artifact: `{m['artifact_hash']}` ({m['artifact_type']}, profile={m['profile']})",
             f"- panel: expected {pi['expected_voters']} / collected {pi['collected_voters']}"
             + (f" · ⚠️missing {pi['missing']}" if pi["missing"] else " · complete ✓"),
             f"- diversity: {div['families']} families"
             + (f" · ⚠️{div['warning']}" if div.get("warning") else ""),
             f"- verified: {len(m.get('verifications', []))} high/critical reviewed by Verifier"
             + " (✓ = verified, may hard-gate; ? = unverified, advisory)",
             f"- surviving objections: {len([c for c in m['concerns'] if c['status'] != 'rebutted'])}"
             + (f" · dropped {len(m['dropped_concerns'])}" if m.get("dropped_concerns") else "")
             + (f" · rebutted {len([c for c in m['concerns'] if c['status']=='rebutted'])}"
                if any(c['status'] == 'rebutted' for c in m['concerns']) else ""), ""]
    for c in m["concerns"]:
        if c["status"] == "rebutted":
            continue
        mark = "✓" if c.get("severity_verified") else "?"
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
        manifest = run_challenge(args.artifact, args.type, args.profile, _discover_adapters())
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
    return _exit_code(manifest["verdict"], args.enforce)


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
        return "update this CLI to a supported version"
    return ""


def _cmd_doctor(args: argparse.Namespace) -> int:
    any_ready = False
    for cls in _ALL_ADAPTERS:
        a = cls()
        state = a.probe()
        any_ready = any_ready or state == ProbeState.READY
        line = f"{a.backend} ({a.model_family}): {state.value}"
        if state != ProbeState.READY:
            hint = _remediation(a, state)
            if hint:
                line += f"  → {hint}"
        print(line)
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
                     help="map non-approve verdicts to a non-zero exit (CI gate); advisory exits 0 by default")
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
