"""Per-artifact-type rubric registry: failure_type enum + review personas + the noun used to
frame the prompt + whether frontmatter preflight applies.

What's shared across types is the manifest/rounds/adapters/verdict pipeline; what differs is the
**rubric and the failure_type enum**. A type whose enum isn't defined isn't allowed into `run`
(otherwise the canonical concern key can't be computed). This module is the registry of the
"defined" types: spec / diff / plan / decision are implemented. A type whose enum is undefined
makes get_rubric raise NotImplementedError, which the CLI turns into a friendly exit.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schema import DecisionFailureType, DiffFailureType, PlanFailureType, SpecFailureType


# Spec review lenses: multiple personas on one subscription widen coverage.
SPEC_PERSONAS: dict[str, str] = {
    "execution-failure": "You care only about: executing this plan, where is it most likely to "
                         "fail or cause rework.",
    "correctness": "You care only about: internal contradictions, unverifiable claims, hidden "
                   "dependencies.",
    "scope-boundary": "You care only about: scope creep, missing non-goals, out-of-scope work, "
                      "and permission/security boundaries.",
}

# Diff review lenses (regression / test-coverage / call sites / edge conditions).
DIFF_PERSONAS: dict[str, str] = {
    "regression": "You care only about: which existing behaviors this change breaks — call sites "
                  "not updated in lockstep, broken interfaces/contracts, regressions.",
    "correctness-security": "You care only about: logic / edge-case bugs introduced, swallowed "
                            "error handling, security and privacy risks.",
    "test-coverage": "You care only about: whether the behavior change has matching test "
                     "coverage, and whether performance / backward-compatibility is quietly broken.",
}

# Generic plan review lenses (domain-neutral — works for a trip, a launch, a hire, a move).
PLAN_PERSONAS: dict[str, str] = {
    "feasibility": "You care only about: can this plan actually be carried out under real "
                   "constraints (time, budget, people, energy) — which step is most likely to stall "
                   "or be impossible.",
    "risk": "You care only about: where this plan is most likely to go wrong, what is most costly "
            "or irreversible, and which known risks have no mitigation or fallback.",
    "goal-alignment": "You care only about: whether the stated goal is well-defined, whether the "
                      "steps actually achieve it, which assumptions must hold, and whether a simpler "
                      "path exists.",
}


# Decision review lenses: audit a choice already made — fair alternatives, evidence strength,
# reversibility/downside. Domain-neutral (a hire, a vendor, a tech-stack pick, a strategy call).
DECISION_PERSONAS: dict[str, str] = {
    "alternatives": "You care only about: which other options were available and whether they were "
                    "fairly considered — the road not taken, false dichotomies, an option space "
                    "narrowed prematurely.",
    "evidence": "You care only about: whether the reasoning rests on real evidence proportional to "
                "the stakes, which claims are unverifiable, which assumptions must hold, and whether "
                "past investment or inertia is doing the arguing.",
    "reversibility-cost": "You care only about: how hard or costly this is to undo, whether the "
                          "chosen option's downsides have mitigations, and whether there is a "
                          "measurable success definition and a trigger to revisit or reverse it.",
}


@dataclass(frozen=True)
class Rubric:
    artifact_type: str
    artifact_noun: str                       # plain-language noun used to frame the prompt
    failure_types: tuple[str, ...]           # challengers must choose failure_type from these
    personas: dict[str, str]                 # persona_key -> review lens
    profile_personas: dict[str, list[str]]   # fast/standard/deep -> persona keys
    frontmatter_preflight: bool              # whether to run the frontmatter/field preflight


# contract_violation is a synthetic type injected by the field preflight, not a challenger choice;
# exclude it from the challenger enum.
_SPEC_FAILURE_TYPES = tuple(t.value for t in SpecFailureType if t.value != "contract_violation")
_DIFF_FAILURE_TYPES = tuple(t.value for t in DiffFailureType)
_PLAN_FAILURE_TYPES = tuple(t.value for t in PlanFailureType)
_DECISION_FAILURE_TYPES = tuple(t.value for t in DecisionFailureType)


SPEC_RUBRIC = Rubric(
    artifact_type="spec",
    artifact_noun="plan/spec",
    failure_types=_SPEC_FAILURE_TYPES,
    personas=SPEC_PERSONAS,
    profile_personas={
        "fast": ["execution-failure"],
        "standard": ["execution-failure", "correctness", "scope-boundary"],
        "deep": ["execution-failure", "correctness", "scope-boundary"],
    },
    frontmatter_preflight=True,
)

DIFF_RUBRIC = Rubric(
    artifact_type="diff",
    artifact_noun="code change (diff)",
    failure_types=_DIFF_FAILURE_TYPES,
    personas=DIFF_PERSONAS,
    profile_personas={
        "fast": ["regression"],
        "standard": ["regression", "correctness-security", "test-coverage"],
        "deep": ["regression", "correctness-security", "test-coverage"],
    },
    # A diff has no frontmatter, so don't inject acceptance_criteria/non_goals synthetic concerns.
    frontmatter_preflight=False,
)

PLAN_RUBRIC = Rubric(
    artifact_type="plan",
    artifact_noun="plan",
    failure_types=_PLAN_FAILURE_TYPES,
    personas=PLAN_PERSONAS,
    profile_personas={
        "fast": ["feasibility"],
        "standard": ["feasibility", "risk", "goal-alignment"],
        "deep": ["feasibility", "risk", "goal-alignment"],
    },
    # A generic plan is free prose (no required frontmatter fields). A missing success criterion
    # surfaces as a model finding (missing_success_criteria), not a mechanical preflight gate —
    # keeping plan review light enough for any domain.
    frontmatter_preflight=False,
)

DECISION_RUBRIC = Rubric(
    artifact_type="decision",
    artifact_noun="decision",
    failure_types=_DECISION_FAILURE_TYPES,
    personas=DECISION_PERSONAS,
    profile_personas={
        "fast": ["alternatives"],
        "standard": ["alternatives", "evidence", "reversibility-cost"],
        "deep": ["alternatives", "evidence", "reversibility-cost"],
    },
    # A decision record is free prose (no required frontmatter fields), like a generic plan —
    # missing success criteria / review triggers surface as model findings (no_review_trigger),
    # not a mechanical preflight gate.
    frontmatter_preflight=False,
)

_RUBRICS: dict[str, Rubric] = {
    r.artifact_type: r
    for r in (SPEC_RUBRIC, DIFF_RUBRIC, PLAN_RUBRIC, DECISION_RUBRIC)
}


def get_rubric(artifact_type: str) -> Rubric:
    """Return the rubric for this type; types without a defined failure_type enum are refused."""
    try:
        return _RUBRICS[artifact_type]
    except KeyError:
        raise NotImplementedError(
            f"--type {artifact_type} is not runnable yet: its failure_type set is not defined."
        )
