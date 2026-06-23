"""Minimal artifact preflight: frontmatter parsing and three-tier field grading.

- Invalid required_to_parse fields such as artifact_type -> schema_invalid, with no model run.
- Missing required_to_approve fields such as acceptance_criteria / non_goals -> inject a
  synthetic CONTRACT_VIOLATION concern that is mechanically verifiable, sets
  severity_verified=True, and participates in verdict resolution.
- Missing optional_context -> caller-level downgrade; v0 only records it and does not enforce.

Lenient policy: bare markdown without frontmatter can still run; artifact_type comes from
--type. Missing fields are loosely recognized from body headings; only when absent there
do we inject synthetic concerns, which is exactly the defect that should be surfaced.
"""
from __future__ import annotations

import re

from .prompts import current_lang
from .schema import Concern, Severity

try:
    import yaml
except ImportError:  # pyyaml is a declared dependency; if absent, degrade to "no frontmatter".
    yaml = None

# Compatible with CRLF / no trailing newline; after --- on the same line, only whitespace then newline is allowed.
_FM = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$", re.DOTALL)

# required_to_approve: missing fields inject synthetic concerns (title, severity).
_REQUIRED_TO_APPROVE = {
    "acceptance_criteria": ("Missing measurable acceptance criteria; completion cannot be determined", Severity.HIGH),
    "non_goals": ("Missing explicit non-goals; scope can easily creep", Severity.MEDIUM),
}
# Synthetic concerns are built in Python and never pass through a model, so --lang can't localize
# them via the prompt. Localized title/evidence live here; languages without an entry fall back to
# the English literals above. Add a `<code>: {field: (title, evidence)}` block to localize a new one.
_LOCALIZED_SYNTHETIC: dict[str, dict[str, tuple[str, str]]] = {
    "zh": {
        "acceptance_criteria": ("缺少可度量的验收标准，无法判定是否完成", "artifact 未提供 acceptance_criteria"),
        "non_goals": ("缺少明确的非目标，范围容易蔓延", "artifact 未提供 non_goals"),
    },
}


def _synthetic_text(name: str, default_title: str) -> tuple[str, str]:
    """(title, evidence) for a synthetic concern, localized to CHALLENGE_PLANS_LANG when available."""
    table = _LOCALIZED_SYNTHETIC.get(current_lang())
    if table and name in table:
        return table[name]
    return default_title, f"artifact does not provide {name}"
# Without frontmatter, recognize these sections only from heading lines starting with #.
# This avoids false positives from prose such as "there are no acceptance criteria yet",
# which would skip synthetic injection and incorrectly pass.
_HEADING_HINTS = {
    "acceptance_criteria": ["acceptance", "completion criteria", "done when", "accept criteria"],
    "non_goals": ["non-goal", "non goal", "out of scope"],
}
_VALID_TYPES = {"spec", "plan", "diff", "decision"}


def parse_artifact(text: str) -> tuple[dict, str]:
    """Return (frontmatter fields dict, body). Without frontmatter, fields={} and body is full text."""
    m = _FM.match(text)
    if m and yaml is not None:
        try:
            fields = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            fields = {}
        return (fields if isinstance(fields, dict) else {}), m.group(2)
    return {}, text


def parse_invalid(fields: dict) -> bool:
    """required_to_parse gate: invalid frontmatter artifact_type -> schema_invalid."""
    at = fields.get("artifact_type")
    return at is not None and at not in _VALID_TYPES


def _field_present(name: str, fields: dict, body: str) -> bool:
    if fields.get(name):
        return True
    # Only heading lines starting with # count; avoid full-body substring matching.
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            low = s.lower()
            if any(h.lower() in low for h in _HEADING_HINTS.get(name, [])):
                return True
    return False


def preflight_concerns(fields: dict, body: str) -> list[Concern]:
    """Missing required_to_approve fields -> synthetic, mechanically verifiable CONTRACT_VIOLATION."""
    out: list[Concern] = []
    for name, (title, sev) in _REQUIRED_TO_APPROVE.items():
        if not _field_present(name, fields, body):
            loc_title, evidence = _synthetic_text(name, title)
            out.append(Concern(
                artifact_span="L1", failure_type="contract_violation", severity=sev,
                title=loc_title, violated_contract_field=name, evidence=evidence,
                synthetic=True, severity_verified=True, raised_by="preflight"))
    return out
