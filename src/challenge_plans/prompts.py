"""Challenger prompt template.

Challenger discipline: steelman first -> at most the profile-specific number of concerns ->
each concern must bind to concrete artifact line anchors -> failure_type must come from the
rubric enum for that artifact type -> no hedging. Output strict JSON and end with END_MARKER
for §9a integrity checks; missing marker means truncation.

Type-specific differences such as noun, lens, and failure_types are injected by the rubric;
this module only frames the task and enforces discipline.
"""
from __future__ import annotations

END_MARKER = "===CHALLENGE_PLANS_END==="


def build_challenger_prompt(artifact_text: str, artifact_noun: str, lens: str,
                            failure_types: tuple[str, ...], max_findings: int) -> str:
    types = ", ".join(failure_types)
    return f"""You are an adversarial {artifact_noun} review challenger. {lens}

Below is the {artifact_noun} with line numbers. Line numbers are anchors, not content:
--- ARTIFACT START ---
{artifact_text}
--- ARTIFACT END ---

Rules you must follow:
1. Start with a one-sentence steelman: what this {artifact_noun} gets right.
2. Raise at most {max_findings} concerns; raise 0 if there are none. **Do not invent issues.**
3. Every concern must bind to a specific line anchor such as "L12-15"; choose failure_type from this enum: [{types}];
   state the most likely step where execution would fail; evidence must quote specific text from the artifact.
4. No hedging.

Output the following **strict JSON** only, with no extra explanation, followed by {END_MARKER} on its own final line:
{{
  "steelman": "<one sentence>",
  "concerns": [
    {{"artifact_span": "L<start>-<end>", "failure_type": "<one enum value>",
      "severity": "critical|high|medium|low", "title": "<short title>",
      "evidence": "<specific text from the artifact>", "concrete_failure_step": "<most likely failing step>"}}
  ]
}}
{END_MARKER}"""
