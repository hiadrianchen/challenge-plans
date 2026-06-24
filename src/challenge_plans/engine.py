"""Adversarial-mode loop: read artifact → parallel challengers → integrity capture →
parse into Concerns → dedup by canonical key (keep strictest) → single verdict pipeline → run manifest.

Multi-persona across the available subscription CLIs, run in parallel. `--deep` runs multiple
rounds: each later round sees the concerns already found and is asked for NEW ones only, and the
loop stops when a round surfaces nothing new (convergence) or hits the round cap. A cross-family
Verifier and a minimal frontmatter/field preflight are implemented; a malformed challenger reply
gets one schema-repair retry before the voter is dropped. Current limitation: no idle-timeout
(wall-clock only). See the CLI `--enforce` flag and the manifest.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re

from .adapters import VoterSpec, strip_marker
from .rubric import SPEC_RUBRIC, get_rubric
from .schema import (
    Concern, PanelIntegrity, Severity, Verdict,
    resolve_verdict, severity_rank, stricter_verdict,
)

# Default panel lenses for deliberation mode: type-agnostic voting perspectives reused from the spec rubric.
_PROFILE_PERSONAS = SPEC_RUBRIC.profile_personas
_PROFILE_MAX_FINDINGS = {"fast": 1, "standard": 3, "deep": 3}
# --deep iterates until a round finds nothing new (convergence) or hits this cap; fast/standard = 1 round.
_PROFILE_MAX_ROUNDS = {"fast": 1, "standard": 1, "deep": 3}


def _prior_summaries(concerns_by_key: dict) -> list[str]:
    """Compact list of already-found concerns to hand the next --deep round (so it finds NEW ones)."""
    return [f"{c.artifact_span} {c.failure_type}: {c.title}" for c in concerns_by_key.values()]


# Schema-repair: appended on a single retry when a challenger's output didn't parse, to recover a
# transient malformed/truncated reply instead of silently dropping that voter.
_REPAIR_HINT = ("\n\nIMPORTANT: your previous reply could not be parsed. Reply with ONLY the strict "
                "JSON object specified above and the final marker line — no other text.")
_SPAN_RE = re.compile(r"^L(\d+)(?:-L?(\d+))?$")
_DECODER = json.JSONDecoder()


def _number_lines(text: str) -> str:
    return "\n".join(f"L{i}: {ln}" for i, ln in enumerate(text.splitlines(), 1))


def _extract_json(text: str) -> dict | None:
    """Use raw_decode to tolerate strings/escapes; require exactly one top-level object before the marker."""
    objs, i = [], text.find("{")
    while i != -1:
        try:
            obj, end = _DECODER.raw_decode(text, i)
            if isinstance(obj, dict):
                objs.append(obj)
            i = text.find("{", end)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    return objs[0] if len(objs) == 1 else None


def _valid_span(span: str, nlines: int) -> bool:
    m = _SPAN_RE.match(span.strip())
    if not m:
        return False
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return 1 <= a <= b <= nlines


def _parse_concerns(raw: dict, voter_id: str, nlines: int,
                    dropped: list[dict], valid_failure_types: set[str]) -> list[Concern]:
    out: list[Concern] = []
    for c in raw.get("concerns", []) or []:
        ftype = c.get("failure_type", "")
        span = (c.get("artifact_span") or "").strip()
        # Panel integrity: dropped items must be recorded in dropped_concerns, never silently continued.
        if ftype not in valid_failure_types:
            dropped.append({"voter": voter_id, "reason": "failure_type_out_of_enum", "raw": c})
            continue
        if not _valid_span(span, nlines):
            dropped.append({"voter": voter_id, "reason": "invalid_or_hallucinated_span", "raw": c})
            continue
        try:
            sev = Severity(c.get("severity", "medium"))
        except ValueError:
            sev = Severity.MEDIUM
        out.append(Concern(
            artifact_span=span, failure_type=ftype, severity=sev,
            title=c.get("title", ""), evidence=c.get("evidence", ""),
            concrete_failure_step=c.get("concrete_failure_step", ""),
            raised_by=voter_id,
        ))
    return out


def _build_panel(profile: str, adapters: list, personas: list[str] | None = None) -> list[tuple]:
    """Round-robin personas over available adapters for cross-family coverage.

    Return [(adapter, persona, voter_id)]. When personas are omitted, use generic
    deliberation lenses; challenge mode passes type-specific lenses from the rubric.
    """
    if personas is None:
        personas = _PROFILE_PERSONAS[profile]
    panel, seen = [], {}
    for i, persona in enumerate(personas):
        adapter = adapters[i % len(adapters)]
        vid = f"{adapter.model_family}:{persona}"
        seen[vid] = seen.get(vid, 0) + 1
        if seen[vid] > 1:
            vid = f"{vid}#{seen[vid]}"
        panel.append((adapter, persona, vid))
    return panel


def run_challenge(artifact_path: str, artifact_type: str, profile: str, adapters) -> dict:
    from .prompts import build_challenger_prompt
    # Reject types without a defined failure_type enum here; plan/decision still raise NotImplementedError.
    rubric = get_rubric(artifact_type)

    from .preflight import parse_artifact, parse_invalid, preflight_concerns
    with open(artifact_path, encoding="utf-8") as f:
        artifact_text = f.read()
    # Non-frontmatter artifacts such as diff skip frontmatter parsing to avoid misreading content.
    fields, body = parse_artifact(artifact_text) if rubric.frontmatter_preflight else ({}, artifact_text)
    nlines = len(body.splitlines())
    artifact_hash = hashlib.sha256(artifact_text.encode()).hexdigest()[:16]

    base = {"mode": "challenge", "artifact_type": artifact_type,
            "artifact_hash": artifact_hash, "rounds": 0, "profile": profile,
            "verifier": "present (cross-family, v0)"}

    def _schema_invalid(reason):
        return {**base, "verdict": Verdict.SCHEMA_INVALID.value, "schema_invalid_reason": reason,
                "panel_integrity": {"expected_voters": 0, "collected_voters": 0,
                                    "missing": [], "complete": False, "action": ""},
                "voters": [], "concerns": [], "dropped_concerns": [], "verifications": [],
                "preflight": {"missing_required_to_approve": []},
                "source_diversity": {"families": 0, "voters": 0, "warning": reason}}

    # Required-to-parse gate, locally decidable before adapter checks: empty artifact -> schema_invalid for every type.
    if nlines == 0 or not body.strip():
        return _schema_invalid("empty_artifact")
    # Frontmatter consistency only applies to frontmatter artifacts such as specs; diff has no such gate.
    if rubric.frontmatter_preflight:
        if parse_invalid(fields):
            return _schema_invalid(f"invalid_artifact_type:{fields.get('artifact_type')}")
        if fields.get("artifact_type") and fields["artifact_type"] != artifact_type:
            return _schema_invalid(f"artifact_type_mismatch:{fields['artifact_type']}!=--type {artifact_type}")

    # From here on challengers must run, so available adapters are required.
    if not adapters:
        raise RuntimeError("No available adapters (all logged out or not installed); run `challenge-plans doctor` first")

    numbered = _number_lines(body)
    max_findings = _PROFILE_MAX_FINDINGS[profile]
    max_rounds = _PROFILE_MAX_ROUNDS[profile]
    valid_failure_types = set(rubric.failure_types)
    panel = PanelIntegrity(expected_voters=0)  # accumulated across rounds

    concerns_by_key: dict[str, Concern] = {}
    raised_by: dict[str, list[str]] = {}
    voters_meta: list[dict] = []
    dropped: list[dict] = []
    families: set[str] = set()
    rounds_run, converged = 0, False

    for rnd in range(1, max_rounds + 1):
        rounds_run = rnd
        voters = _build_panel(profile, adapters, rubric.profile_personas[profile])
        panel.expected_voters += len(voters)
        # Round 2+ is handed what's already been found and asked for NEW concerns only — a round
        # that adds nothing new is what makes --deep converge instead of just repeating round 1.
        prior = _prior_summaries(concerns_by_key) if rnd > 1 else None

        def _run(adapter, persona, voter_id, _prior=None):
            spec = VoterSpec(voter_id=voter_id, backend=adapter.backend,
                             model_family=adapter.model_family, persona=persona)
            prompt = build_challenger_prompt(numbered, rubric.artifact_noun, rubric.personas[persona],
                                             rubric.failure_types, max_findings, prior=_prior)
            cap = adapter.invoke(prompt, spec)
            raw = _extract_json(strip_marker(cap.text)) if cap.ok else None
            repaired = False
            # Retry ONLY on a parse failure (captured output but unparseable JSON). A capture failure
            # (timeout / truncation) is NOT retried — re-invoking would just burn another timeout.
            if cap.ok and raw is None:
                cap2 = adapter.invoke(prompt + _REPAIR_HINT, spec)
                raw2 = _extract_json(strip_marker(cap2.text)) if cap2.ok else None
                if raw2 is not None:
                    cap, raw, repaired = cap2, raw2, True
            return voter_id, spec, cap, raw, repaired

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(voters)) as ex:
            futs = [ex.submit(_run, a, p, v, prior) for a, p, v in voters]
            for fut in futs:
                results.append(fut.result())

        new_keys = 0
        for voter_id, spec, cap, raw, repaired in results:
            meta = {"voter_id": voter_id, "backend": spec.backend, "round": rnd,
                    "model_family": spec.model_family, "transport": spec.transport}
            if not cap.ok:
                panel.missing.append({"voter": voter_id,
                                      "reason": cap.reason.value if cap.reason else "unknown"})
                meta["status"] = "capture_failed"
                voters_meta.append(meta)
                continue
            if raw is None:
                panel.missing.append({"voter": voter_id, "reason": "parse_error"})
                meta["status"] = "parse_error"
                voters_meta.append(meta)
                continue
            panel.collected_voters += 1
            families.add(spec.model_family)
            meta["status"] = "ok"
            if repaired:
                meta["repaired"] = True
            voters_meta.append(meta)
            for c in _parse_concerns(raw, voter_id, nlines, dropped, valid_failure_types):
                existing = concerns_by_key.get(c.key)
                if existing is None:
                    new_keys += 1
                    concerns_by_key[c.key] = c
                elif severity_rank(c.severity) > severity_rank(existing.severity):
                    # Dedup + strictest-wins: keep the highest severity per key.
                    concerns_by_key[c.key] = c
                raised_by.setdefault(c.key, []).append(voter_id)

        # Convergence: a later round that surfaces no NEW concern means there's nothing left to find.
        if rnd > 1 and new_keys == 0:
            converged = True
            break

    # Missing required_to_approve fields inject synthetic contract concerns.
    # Only frontmatter-contract artifacts such as specs get this; diff has no such contract.
    preflight = preflight_concerns(fields, body) if rubric.frontmatter_preflight else []
    for sc in preflight:
        concerns_by_key.setdefault(sc.key, sc)

    concerns = list(concerns_by_key.values())
    # Verifier: produce concrete reproduction for live high/critical concerns -> severity_verified.
    from .verifier import verify_concerns
    verifications = verify_concerns(concerns, numbered, adapters, rubric.artifact_noun)
    verdict = resolve_verdict(concerns, panel=panel)
    # Broken verification infrastructure (capture/parse failure) is not "no objections":
    # it cannot hard-gate and cannot masquerade as approval, so force inconclusive.
    verifier_broken = any(v.get("assessment") in ("capture_failed", "parse_error")
                          for v in verifications)
    if verifier_broken:
        verdict = stricter_verdict(verdict, Verdict.INCONCLUSIVE)
    # A single model family is insufficient for consensus; cap verdict at discuss.
    low_diversity = len(families) <= 1
    if low_diversity:
        verdict = stricter_verdict(verdict, Verdict.DISCUSS)

    return {
        **base,
        "verdict": verdict.value,
        "rounds": rounds_run,
        "convergence": {
            "converged": converged,
            "reason": ("single_round" if max_rounds == 1
                       else "no_new_objections" if converged else "round_cap_reached"),
        },
        "source_diversity": {"families": len(families), "voters": panel.collected_voters,
                             "warning": "low_diversity_single_family" if low_diversity else None},
        "panel_integrity": {"expected_voters": panel.expected_voters,
                            "collected_voters": panel.collected_voters,
                            "missing": panel.missing, "complete": panel.complete,
                            "action": "flagged" if panel.missing else ""},
        "voters": voters_meta,
        "preflight": {"missing_required_to_approve": [c.violated_contract_field for c in preflight]},
        "dropped_concerns": dropped,
        "verifications": verifications,
        "concerns": [
            {"key": c.key, "artifact_span": c.artifact_span, "failure_type": c.failure_type,
             "severity": c.severity.value, "severity_verified": c.severity_verified,
             "verified_by": c.verified_by, "title": c.title, "evidence": c.evidence,
             "concrete_failure_step": c.concrete_failure_step,
             "raised_by": sorted(set(raised_by.get(c.key, [c.raised_by]))),
             "status": c.status.value}
            for c in concerns
        ],
    }
