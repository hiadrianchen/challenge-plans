"""Per-artifact-type rubric registry: failure_type enum + review personas + the noun used to
frame the prompt + whether frontmatter preflight applies.

What's shared across types is the manifest/rounds/adapters/verdict pipeline; what differs is the
**rubric and the failure_type enum**. A type whose enum isn't defined isn't allowed into `run`
(otherwise the canonical concern key can't be computed). This module is the registry of the
"defined" types: spec / diff are implemented; plan / decision are pending (get_rubric raises
NotImplementedError, which the CLI turns into a friendly exit).
"""
from __future__ import annotations

from dataclasses import dataclass

from .schema import DiffFailureType, SpecFailureType


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

_RUBRICS: dict[str, Rubric] = {r.artifact_type: r for r in (SPEC_RUBRIC, DIFF_RUBRIC)}


def get_rubric(artifact_type: str) -> Rubric:
    """Return the rubric for this type; types without a defined failure_type enum are refused."""
    try:
        return _RUBRICS[artifact_type]
    except KeyError:
        raise NotImplementedError(
            f"--type {artifact_type} is not runnable yet: its failure_type set is not defined."
        )
