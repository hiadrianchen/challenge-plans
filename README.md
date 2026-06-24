# challenge-plans

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/hiadrianchen/challenge-plans/ci.yml?branch=main)](https://github.com/hiadrianchen/challenge-plans/actions)

> 中文文档: [README-zh.md](README-zh.md)

**Adversarially review a plan before you execute it — across the AI coding CLIs you already have logged in. No API keys.**

`challenge-plans` orchestrates the subscription CLIs on your machine (Claude Code, Codex, …) to cross-examine a plan and surface the flaws that cause rework — then aggregates only the objections that survive scrutiny into a single verdict. It runs as a CLI, an **agent skill**, or a CI gate, and slots into the superpowers plan lifecycle: `writing-plans → challenge-plans → executing-plans`.

## Why challenge-plans

- 🔑 **No API keys, no per-token charges** — it drives the subscription CLIs you're already logged into (Claude Code, Codex). Bring at least one.
- 🧪 **Evidence beats headcount** — a minority objection with a reproduction can override a majority; correctness isn't decided by voting.
- 🤝 **Cross-family verification** — an objection only earns hard-gate authority (`✓`) when an *independent model family* reproduces it with line-anchored evidence. Single-model claims stay advisory.
- 🛡️ **Guards 7 multi-agent failure modes** — vote loss, option anchoring, premature hand-off, majority-over-minority, single-round complacency, false consensus, false convergence ([how](docs/how-it-works.md)).
- 🌍 **Speaks your language** — `--lang zh` (or `ja`, `de`, …) localizes every finding; one flag, no separate build.

## What it reviews

You don't have to write specs to use this. Three things it does:

- 📋 **Any plan** — a trip, a launch, a hire, a move. `--type plan` checks it for the ways plans go wrong (more below).
- 📝 **A drafted spec or design doc** before you build — `--type spec`.
- 🔧 **A code change** as a lightweight review — `--type diff`. And when you're **torn between options**, `weigh` votes across them with weighted, dissent-exposing deliberation.

## Quickstart

**Easiest — hand it to your agent.** Tell it:

> Install challenge-plans from https://github.com/hiadrianchen/challenge-plans and run `challenge-plans doctor`.

It sets up the package and reports which backends are ready.

**Or install it yourself** (Python ≥ 3.10):

```bash
pip install challenge-plans      # or: pipx install challenge-plans  ·  uvx challenge-plans doctor
challenge-plans doctor           # which CLIs are logged in
```

Bring at least one logged-in CLI — **Claude Code** (`claude`) or **OpenAI Codex** (`codex`); two different vendors unlock cross-family verification. To use it **as an agent skill**, drop [SKILL.md](SKILL.md) where your agent discovers skills. (Developing? `git clone … && pip install -e .`.)

## See it work

Here's the **"any plan"** scenario — one of the three above — on a rough Kyoto-trip plan ([`examples/plan-sample.md`](examples/plan-sample.md)):

```text
$ challenge-plans run examples/plan-sample.md --type plan --sink markdown

# challenge-plans · challenge · verdict: request_changes
- [high✓] Non-refundable flights locked before validating the trip  @L10  (irreversibility_or_high_cost, by claude:feasibility)
- [med ] Day 2 packs six sights across the city — likely undoable   @L4   (ignored_constraint, by gpt:risk)
- [med ] "A good trip" is never defined, so nothing can be judged   @L1   (missing_success_criteria, by claude:goal-alignment)
```

Each line is a **tagged objection** — anchored to a line, raised by one reviewer with a single job. The three findings above came from three reviewers:

- **Feasibility** *(can it actually be done?)* → caught the **non-refundable flight** locked in before the plan is even validated.
- **Risk** *(what's most likely to go wrong / is irreversible?)* → caught **Day 2 cramming six sights** across the city with no time budget.
- **Goal-alignment** *(do the steps serve the goal?)* → caught that **"a good trip" is never defined**, so nothing can be judged.

Every objection is tagged from a fixed menu of *ways a plan breaks* — which keeps findings concrete and de-duplicable. Here's what each one catches, in this trip:

- `irreversibility_or_high_cost` — booking a non-refundable flight before validating the plan
- `ignored_constraint` — six sights in one day, no time or energy budget
- `missing_success_criteria` — never saying what "a good trip" means
- `dependency_or_sequencing_gap` — a 10:00 train right after "last-minute shopping"
- `unaddressed_risk` — going in mid-July with no rain/heat backup
- `unstated_assumption` — assuming the famous kaiseki place has a table
- `no_fallback` — no plan B if that restaurant is booked out
- `goal_misalignment` — a "relaxing" trip scheduled dawn to midnight

`--profile fast` runs one reviewer, `standard` all three (one round); `deep` runs the panel for multiple rounds — each round is shown what's already been found and hunts for what the last one missed — and stops when a round surfaces nothing new (convergence).

## Usage

**As a skill, you don't memorize flags — just ask your agent.** Say *"review this plan with challenge-plans"*, *"is this spec ready to build?"*, or even *"how do I use challenge-plans?"* — it picks the mode and command for you and brings back the surviving objections.

**Running it directly?** Here's the map:

| I want to… | Run |
|---|---|
| See which backends are ready | `challenge-plans doctor` |
| Review **any plan** | `challenge-plans run trip.md --type plan --sink markdown` |
| Review a **spec** before building | `challenge-plans run spec.md --type spec --sink markdown` |
| Review a **code change** | `git diff > c.diff && challenge-plans run c.diff --type diff` |
| **Choose** among options | `challenge-plans weigh options.yaml --sink markdown` |
| Get findings in **Chinese** | add `--lang zh` |
| Use it as a **CI gate** | add `--enforce` (`request_changes` / `inconclusive` / `schema_invalid` exit non-zero; `discuss`/`approve` exit 0) |

`--profile fast|standard|deep` trades speed for depth. `[sev✓]` = an independent model family reproduced it with line-anchored evidence (cross-model *confirmation* — not a mechanically-run test), so it may hard-gate; `[sev?]` = unconfirmed, advisory. Ready-to-run samples live in [`examples/`](examples/). Not pip-installed? Prefix with `PYTHONPATH=src python3 -m challenge_plans.cli …`.

## Output in your language

The codebase is English, but reviewers can answer in **any** language — add `--lang`:

```bash
challenge-plans run plan.md --type plan --lang zh     # findings in Chinese
challenge-plans weigh options.yaml --lang ja          # deliberation in Japanese
```

It switches only the human-readable prose; JSON keys, enum values, and line anchors stay verbatim, so parsing and CI gates are unaffected (equivalent to setting `CHALLENGE_PLANS_LANG`). Your agent can pass `--lang <user-language>` to localize the whole review.

## How it works

Multiple persona/CLI challengers steelman then attack the artifact; a **cross-family Verifier** must reproduce a high/critical objection with line-anchored evidence before it can hard-gate; findings are de-duplicated and resolved into one **6-state verdict** — with an incomplete panel never passing as `approve`. The full mechanism, the two modes, the three-phase deliberation flow, and the 7 failure modes are in **[docs/how-it-works.md](docs/how-it-works.md)**. It also composes with [superpowers](https://github.com/obra/superpowers) and [grill-me](https://github.com/mattpocock/skills) — see there.

## Backends

Drives whatever subscription coding CLI you already have logged in — **Claude Code** (`claude`) or **OpenAI Codex** (`codex`); not tied to any one. Two different vendors cross-verify findings; with one, results stay advisory. No API keys, no per-token charges from this tool. It needs **at least one** logged-in CLI — `challenge-plans doctor` names each backend's state and the exact fix (install, or log in).

## Status

**v1 — usable.** Both modes work end-to-end, validated against real plans/specs, pinned by a pytest suite, and hardened across multiple cross-agent adversarial-review rounds (the README itself included). Known boundaries are listed in [docs/how-it-works.md](docs/how-it-works.md).

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The project is dogfooded: review your own change with `challenge-plans run <change>.diff --type diff` before opening a PR.

## License

[Apache-2.0](LICENSE).
