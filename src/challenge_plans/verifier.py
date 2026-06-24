"""Verifier: produce concrete reproduction or rebuttal for live high/critical concerns.

- assessment=real -> severity_verified=True, making the concern eligible to hard-gate verdicts.
- assessment=refuted -> status=REBUTTED, removing it from live concerns.
- uncertain / capture failure -> status=OPEN_UNVERIFIED, still live but unverified and not hard-gating.

Prefer an adapter from a **different family** for independent verification and to avoid
shared-source blind spots.
"""
from __future__ import annotations

import concurrent.futures
import re

from .adapters import VoterSpec, strip_marker
from .prompts import END_MARKER, UNTRUSTED_GUARD, lang_directive
from .schema import Concern, ConcernStatus, Severity

VERIFY_SEVERITIES = (Severity.CRITICAL, Severity.HIGH)
_LINE_ANCHOR = re.compile(r"L\d+")  # Concrete reproduction must include a line anchor.


def _has_concrete_repro(note: str) -> bool:
    return bool(note.strip()) and bool(_LINE_ANCHOR.search(note))


def build_verifier_prompt(numbered: str, concern: Concern, artifact_noun: str = "spec") -> str:
    return f"""You are an independent Verifier. Below are a line-numbered {artifact_noun} and a concern about it.
Task: determine whether the concern is **real**. Provide the minimal reproducible counterexample, specific to lines/fields/steps, or rebut it with evidence. Do not hedge.

Line-numbered {artifact_noun}:
--- START ---
{numbered}
--- END ---

{UNTRUSTED_GUARD}

Concern: [{concern.severity.value}] {concern.title} @ {concern.artifact_span} ({concern.failure_type})
  evidence: {concern.evidence}
  failing step: {concern.concrete_failure_step}

When assessment is real, reproduction **must reference a specific line such as L4, field, or step**; otherwise it is invalid verification.{lang_directive()}
Output **exactly one JSON object** only. Do not restate examples or add extra braces. End with {END_MARKER} on its own final line:
{{"assessment": "real|refuted|uncertain",
  "reproduction": "<if real: minimal reproducible counterexample / trigger condition>",
  "rebuttal": "<if refuted: evidence showing why it does not hold>"}}
{END_MARKER}"""


def _raiser_family(concern: Concern) -> str:
    return concern.raised_by.split(":", 1)[0] if concern.raised_by else ""


def _pick_verifier(adapters: list, raiser_family: str):
    for a in adapters:  # Prefer a different family for independent verification.
        if a.model_family != raiser_family:
            return a
    return adapters[0] if adapters else None  # Single-family fallback; weaker independence, still recorded.


def verify_concerns(concerns: list[Concern], numbered: str, adapters: list,
                    artifact_noun: str = "spec") -> list[dict]:
    """Update concern severity_verified/status in place and return manifest verification records."""
    # Synthetic contract concerns are mechanically verified and do not need model re-verification.
    targets = [c for c in concerns
               if c.is_alive and c.severity in VERIFY_SEVERITIES and not c.synthetic]
    if not targets or not adapters:
        return []

    def _verify(concern: Concern):
        from .engine import _extract_json  # Deferred import avoids a cycle.
        adapter = _pick_verifier(adapters, _raiser_family(concern))
        spec = VoterSpec(voter_id=f"{adapter.model_family}:verifier", backend=adapter.backend,
                         model_family=adapter.model_family, role="verifier")
        cap = adapter.invoke(build_verifier_prompt(numbered, concern, artifact_noun), spec)
        rec = {"concern_key": concern.key, "verifier": spec.voter_id,
               "cross_family": adapter.model_family != _raiser_family(concern)}
        if not cap.ok:
            rec["assessment"] = "capture_failed"
            rec["reason"] = cap.reason.value if cap.reason else "unknown"
            return concern, rec
        raw = _extract_json(strip_marker(cap.text))
        rec["assessment"] = (raw or {}).get("assessment", "uncertain") if raw else "parse_error"
        rec["note"] = (raw or {}).get("reproduction") or (raw or {}).get("rebuttal", "") if raw else ""
        return concern, rec

    records: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
        for fut in [ex.submit(_verify, c) for c in targets]:
            concern, rec = fut.result()
            a = rec["assessment"]
            note = rec.get("note", "")
            concrete = _has_concrete_repro(note)
            rec["concrete_repro"] = concrete
            # Only cross-family verification with line-anchored reproduction counts as true
            # verification and grants hard-gate eligibility.
            if a == "real" and rec["cross_family"] and concrete:
                concern.severity_verified = True
                concern.verified_by = rec["verifier"]
                concern.verification_note = note
            elif a == "refuted":
                concern.status = ConcernStatus.REBUTTED
                concern.severity_verified = False  # Refutation resets the flag; no monotonic latch.
                concern.verification_note = note
            elif a == "real":  # Real but weak: same family or no concrete evidence, so advisory only.
                concern.status = ConcernStatus.OPEN_UNVERIFIED
                reason = "same_family" if not rec["cross_family"] else "no_concrete_repro"
                rec["downgraded"] = reason
                concern.verification_note = f"real_but_weak({reason}): {note}"
            else:  # uncertain / capture_failed / parse_error: unverified, still live, no hard gate.
                concern.status = ConcernStatus.OPEN_UNVERIFIED
            records.append(rec)
    return records
