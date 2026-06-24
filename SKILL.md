---
name: challenge-plans
description: Before you execute a drafted plan/spec/design doc, run a multi-agent adversarial cross-review to surface the flaws that cause downstream rework, aggregating "evidenced, cross-family-verified" objections into a verdict. Use when the user asks to "review this plan/spec", "can this approach be executed", "poke holes / adversarial review / QA this", "harden before executing", or when an agent is about to hand a drafted decision/QA back to the user — first run this skill and present the cross-review recommendation plus surviving objections. Runs on local subscription CLIs (claude/codex), no per-token API cost. Not for "help me pick among options" — that's the weigh-options deliberation skill.
runtime_mode: cli_tool
---

# challenge-plans

Harden a plan/spec in multi-agent adversarial review before execution, to reduce rework. Slots into `writing-plans → challenge-plans → executing-plans`.

## When to use (routing signals)

- Input is a **single drafted artifact** (spec/plan/diff/design doc/adr) + intent "review / find flaws / can this execute / harden / QA" → **use this skill**.
- An agent has finished something and is **about to ask the user to decide or QA** → run this first and present the cross-review recommendation.
- Input is **≥2 options to choose from** → use the sibling `weigh-options` (deliberation/voting), not this.

## Run

```bash
cd challenge-plans
PYTHONPATH=src python3 -m challenge_plans.cli doctor   # check adapter login state first
PYTHONPATH=src python3 -m challenge_plans.cli run <artifact> --type spec --profile standard --sink markdown
# uvx form: uvx --from . challenge-plans run <artifact> --type spec --profile standard --sink markdown
# code-diff gate: git diff > change.diff && ... run change.diff --type diff --profile standard --sink markdown
```

- `--type spec|diff` (plan/decision rubric still pending — those exit 2 by design). `diff` reviews a raw `git diff` for regression/correctness/test-coverage with the same verdict pipeline.
- `--profile fast|standard|deep`, `--sink stdout|markdown`, `--enforce` (non-approve verdicts exit non-zero; default advisory exits 0).
- `--lang <code>` (default `en`): write the review prose in the user's language, e.g. `--lang zh`. **Set this from the user's language** so the whole review comes back localized; JSON keys / enums / `L12-15` anchors stay stable. Equivalent to exporting `CHALLENGE_PLANS_LANG`.
- Output: a 6-state verdict + surviving objections. `[sev✓]` = cross-family Verifier-confirmed, may hard-gate; `[sev?]` = unverified, advisory only.

## Presenting to the user

Surface the verdict + **surviving objections (✓ verified vs ? unverified)** + missing required fields as "my cross-review recommendation", then let the user decide — rather than handing them a bare decision. See [README.md](README.md) for the full picture.
