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
# Installed from PyPI (pip install challenge-plans) — the console command is available directly:
challenge-plans doctor                                                            # check adapter login state first
challenge-plans run <artifact> --type spec --profile standard --sink markdown     # review a plan/spec
challenge-plans run <artifact> --type spec --profile standard --sink markdown --lang zh   # localized output
# code-diff gate:  git diff > change.diff && challenge-plans run change.diff --type diff --sink markdown
# From a source checkout instead (not pip-installed): PYTHONPATH=src python3 -m challenge_plans.cli <args>
```

- `--type spec|diff` (plan/decision rubric still pending — those exit 2 by design). `diff` reviews a raw `git diff` for regression/correctness/test-coverage with the same verdict pipeline.
- `--profile fast|standard|deep`, `--sink stdout|markdown`, `--enforce` (non-approve verdicts exit non-zero; default advisory exits 0).
- `--lang <code>` (default `en`): write the review prose in the user's language, e.g. `--lang zh`. **Set this from the user's language** so the whole review comes back localized; JSON keys / enums / `L12-15` anchors stay stable. Equivalent to exporting `CHALLENGE_PLANS_LANG`.
- Output: a 6-state verdict + surviving objections. `[sev✓]` = cross-family Verifier-confirmed, may hard-gate; `[sev?]` = unverified, advisory only.

## If no backend is ready

challenge-plans needs **at least one logged-in subscription CLI** (it has no model of its own and uses no API keys). If `doctor` shows nothing `ready`, don't retry blindly — **ask the user, then route**:
1. **Has a Claude or ChatGPT subscription, but the CLI is missing / logged out** → walk them through the exact step `doctor` prints (install it, or `claude` → `/login`, or sign in to `codex`).
2. **No subscription yet but wants one** → point them to subscribe (Claude Pro/Max or ChatGPT), then install + log in the CLI.
3. **No subscription and doesn't want one** → explain challenge-plans cannot run without one, and stop — don't loop.

`doctor` already prints the per-backend fix plus this guidance; surface it to the user rather than failing silently.

## Presenting to the user

Surface the verdict + **surviving objections (✓ verified vs ? unverified)** + missing required fields as "my cross-review recommendation", then let the user decide — rather than handing them a bare decision. See [README.md](README.md) for the full picture.

## Composing with planning skills

- **superpowers** (`writing-plans → executing-plans`): after `writing-plans` saves a plan file (default `docs/superpowers/plans/<date>-<feature>.md` — read the actual path), run `challenge-plans run <plan> --type spec` **before** `executing-plans`. It occupies the same pre-execution review seam as superpowers' built-in `plan-document-reviewer`, but as a multi-CLI cross-family pass. Route surviving objections back into the plan, then execute.
- **grill-me** (mattpocock/skills): complementary and earlier — it interactively aligns the user while the plan forms (no file output). Run challenge-plans *after* a written plan/PRD exists.
- Nothing auto-invokes challenge-plans; the calling agent wires it into the seam. `--type plan`/`decision` rubrics are pending — use `--type spec` for plan-like prose today.
