"""Core data model plus the single verdict pipeline.

This is the previously unverified logic in the design: concern identity, verdict priority,
and panel integrity. v0 first turns it into importable, unit-testable code; the next round
will run adversarial review on the code itself.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


# ── Verdict states plus contract gate state, ordered strictest first ──
class Verdict(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    REQUEST_CHANGES = "request_changes"
    INCONCLUSIVE = "inconclusive"  # Includes incomplete panels; never masquerade as approve.
    DISCUSS = "discuss"
    APPROVE_WITH_UNVERIFIED_TIMEOUTS = "approve_with_unverified_timeouts"
    APPROVE = "approve"


# Priority: lower index is stricter; resolution takes the strictest matching state.
VERDICT_PRECEDENCE: list[Verdict] = [
    Verdict.SCHEMA_INVALID,
    Verdict.REQUEST_CHANGES,
    Verdict.INCONCLUSIVE,
    Verdict.DISCUSS,
    Verdict.APPROVE_WITH_UNVERIFIED_TIMEOUTS,
    Verdict.APPROVE,
]


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConcernStatus(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    FIXED = "fixed"          # Only Verifier sets this after close conditions.
    REBUTTED = "rebutted"    # Only Verifier sets this from counterevidence.
    OPEN_UNVERIFIED = "open_unverified"            # Verifier timeout; downgrade without refuting.
    CONFIRMED_UNVERIFIED = "confirmed_unverified"


# failure_type enum for spec. plan/decision remain unsupported until their enums exist.
class SpecFailureType(str, Enum):
    AMBIGUITY_TO_WRONG_IMPLEMENTATION = "ambiguity_to_wrong_implementation"
    MISSING_ACCEPTANCE_TEST = "missing_acceptance_test"
    HIDDEN_DEPENDENCY = "hidden_dependency"
    SCOPE_CREEP = "scope_creep"
    UNVERIFIABLE_CLAIM = "unverifiable_claim"
    ROLLOUT_OR_OPERATIONAL_RISK = "rollout_or_operational_risk"
    SECURITY_OR_PRIVACY_BOUNDARY = "security_or_privacy_boundary"
    INTEGRATION_CONTRACT_GAP = "integration_contract_gap"
    CONTRACT_VIOLATION = "contract_violation"  # Synthetic concern injected for missing required fields.


# failure_type enum for diff/code changes, covering adversarial review of git diffs:
# behavior regressions, test coverage, call sites, edge cases, contracts, and security.
class DiffFailureType(str, Enum):
    CORRECTNESS_BUG = "correctness_bug"                  # Introduced logic or edge-case bug.
    REGRESSION_RISK = "regression_risk"                  # Existing behavior or call sites broken.
    MISSING_TEST = "missing_test"                        # Behavior change lacks matching tests.
    CONTRACT_BREAK = "contract_break"                    # Public API/interface/data/exit-code contract broken.
    ERROR_HANDLING_GAP = "error_handling_gap"            # New path lacks error handling or swallows exceptions.
    PERF_REGRESSION = "perf_regression"                  # Clear performance regression such as N+1 or hot-path allocation.
    SECURITY_OR_PRIVACY_RISK = "security_or_privacy_risk"  # Injection point, missing auth, or sensitive data exposure.
    BACKWARD_COMPAT_BREAK = "backward_compat_break"      # Backward-compatible schema/serialization/config contract broken.


# ── Concern identity: canonical keys prohibit free-text identity ──
def canonical_key(
    *, artifact_span: str, failure_type: str,
    violated_contract_field: str = "", concrete_failure_step: str = "",
    trigger_condition: str = "",
) -> str:
    """key = hash(mechanical anchor + failure_type + violated field + failing step + trigger condition).

    artifact_span must be a mechanically locatable anchor such as a line range or item id;
    callers are responsible for guaranteeing that. This function only computes deterministic
    fingerprints. Text similarity may help clustering, but never verdict resolution.
    """
    if not artifact_span:
        raise ValueError("artifact_span cannot be empty: concerns must bind to mechanical anchors; free-text identity is not allowed")
    raw = "\x1f".join([artifact_span, failure_type, violated_contract_field,
                       concrete_failure_step, trigger_condition])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Concern:
    artifact_span: str
    failure_type: str
    severity: Severity
    title: str = ""
    evidence: str = ""             # Must bind to specific artifact text.
    reproduction: str = ""         # Verifier's minimal reproduction or contradictory source line.
    raised_by: str = ""            # voter_id
    status: ConcernStatus = ConcernStatus.OPEN
    violated_contract_field: str = ""
    concrete_failure_step: str = ""
    trigger_condition: str = ""
    generation: int = 0            # Multi-round generation.
    parent_concern_id: str | None = None
    synthetic: bool = False        # True = injected by a contract violation, not a model finding.
    severity_verified: bool = False  # True only after Verifier produces concrete reproduction.
    verified_by: str = ""            # Verifier voter_id.
    verification_note: str = ""      # Reproduction/counterevidence summary.

    @property
    def key(self) -> str:
        return canonical_key(
            artifact_span=self.artifact_span, failure_type=self.failure_type,
            violated_contract_field=self.violated_contract_field,
            concrete_failure_step=self.concrete_failure_step,
            trigger_condition=self.trigger_condition,
        )

    @property
    def is_alive(self) -> bool:
        return self.status in (
            ConcernStatus.OPEN, ConcernStatus.CONFIRMED,
            ConcernStatus.OPEN_UNVERIFIED, ConcernStatus.CONFIRMED_UNVERIFIED,
        )


# ── Panel integrity ─────────────────────────────────────────────────────────
class CaptureFailureReason(str, Enum):
    TIMEOUT = "timeout"
    TRUNCATED = "truncated"
    PARSE_ERROR = "parse_error"
    EMPTY = "empty"
    EXIT_NONZERO = "exit_nonzero"


@dataclass
class PanelIntegrity:
    expected_voters: int = 0
    collected_voters: int = 0
    missing: list[dict] = field(default_factory=list)  # [{voter, reason}]
    action: str = ""  # retried | flagged

    @property
    def complete(self) -> bool:
        return not self.missing and self.collected_voters >= self.expected_voters


# ── Single verdict pipeline: all verdicts are emitted once here, strictest wins ──
def resolve_verdict(
    concerns: list[Concern],
    *,
    schema_invalid: bool = False,
    panel: PanelIntegrity | None = None,
    has_unverified_timeout: bool = False,
) -> Verdict:
    """Mechanically derive one verdict from concerns plus gate signals; models do not decide.

    Missing required fields should be injected by the caller as synthetic CONTRACT_VIOLATION
    concerns, so they naturally flow through this pipeline and are not handled
    separately here.
    """
    if schema_invalid:
        return Verdict.SCHEMA_INVALID

    alive = [c for c in concerns if c.is_alive]
    # Only **verified** high/critical concerns can hard-gate.
    # Unverified high/critical concerns cannot request_changes; they downgrade to discuss.
    if any(c.severity in (Severity.CRITICAL, Severity.HIGH) and c.severity_verified
           for c in alive):
        return Verdict.REQUEST_CHANGES

    # Incomplete panels never masquerade as approve; inconclusive outranks discuss.
    if panel is not None and not panel.complete:
        return Verdict.INCONCLUSIVE

    # Unverified high/critical or medium concerns -> discuss; objections exist but do not hard-gate.
    if any(c.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM) for c in alive):
        return Verdict.DISCUSS
    if has_unverified_timeout:
        return Verdict.APPROVE_WITH_UNVERIFIED_TIMEOUTS
    return Verdict.APPROVE


def stricter_verdict(a: Verdict, b: Verdict) -> Verdict:
    """Return the stricter verdict by VERDICT_PRECEDENCE; lower index is stricter."""
    return a if VERDICT_PRECEDENCE.index(a) <= VERDICT_PRECEDENCE.index(b) else b


_SEVERITY_RANK = {Severity.CRITICAL: 3, Severity.HIGH: 2, Severity.MEDIUM: 1, Severity.LOW: 0}


def severity_rank(s: Severity) -> int:
    return _SEVERITY_RANK[s]
