# challenge-plans

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue.svg)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/hiadrianchen/challenge-plans/ci.yml?branch=main)](https://github.com/hiadrianchen/challenge-plans/actions)

> 中文文档: [README-zh.md](README-zh.md)

**Adversarially review your plan or spec before you execute it — across the coding CLIs you already have logged in. No API keys.**

`challenge-plans` orchestrates the subscription AI coding CLIs already on your machine (Claude Code, Codex, …) to cross-examine a plan/spec and surface the flaws that cause rework downstream — and to vote across options when you're unsure. It also reviews a raw `git diff` as a lightweight **code review** pass, and drops in as an **agent skill**. It runs on your existing subscriptions, so there are no per-token API charges. It slots into the superpowers plan lifecycle: `writing-plans → challenge-plans → executing-plans`.

```text
$ challenge-plans run plan.md --type spec --profile standard --sink markdown

# challenge-plans · challenge · verdict: request_changes
- panel: expected 3 / collected 3 · complete ✓
- diversity: 2 families
- verified: 3 high/critical reviewed by Verifier (✓ verified, may hard-gate; ? unverified, advisory)
- surviving objections: 4

- [high✓]   sensitive data sent to a third-party LLM with no privacy boundary  @L42-43  (security_or_privacy_boundary, by claude:scope-boundary)
- [high✓]   "schema-aligned" claimed but there's no contract test             @L12-30  (integration_contract_gap, by gpt:correctness)
- [high✓]   no measurable acceptance threshold                               @L1      (contract_violation, by preflight)
- [medium?] missing_fields vs null semantics left undefined                  @L32-34  (ambiguity_to_wrong_implementation)
```

## Why challenge-plans

- 🔑 **No API keys, no per-token charges** — it drives the subscription CLIs you're already logged into (Claude Code, Codex). Bring at least one.
- 🧪 **Evidence beats headcount** — a minority objection with a reproduction can override a majority vote; correctness is not decided by voting.
- 🤝 **Cross-family verification** — an objection only earns hard-gate authority (`✓`) when an *independent model family* reproduces it with concrete, line-anchored evidence. Single-model claims stay advisory.
- 🛡️ **Guards 7 known multi-agent failure modes** — vote loss, option anchoring, premature hand-off, majority-over-minority, single-round complacency, false consensus, false convergence. Each was hit (and fixed) while building this tool with its own adversarial process.
- 🌍 **Reads in your language** — the codebase is English, but `--lang zh` (or `ja`, `de`, `fr`, …) makes every reviewer write its findings in your language while JSON keys and line anchors stay machine-stable. One flag, no separate build — see [Output in your language](#output-in-your-language).

## Quickstart

Requires Python ≥ 3.10 (PyYAML installs automatically). Bring at least one logged-in coding CLI — **Claude Code** (`claude`) or **OpenAI Codex** (`codex`); two different vendors unlock cross-family verification.

```bash
pip install challenge-plans      # or: pipx install challenge-plans  ·  uvx challenge-plans doctor
challenge-plans doctor           # which backend CLIs are logged in
challenge-plans run your-plan.md --type spec --sink markdown   # get a verdict on your own plan/spec
```

Want the bundled sample, or to hack on it? Clone instead:

```bash
git clone https://github.com/hiadrianchen/challenge-plans && cd challenge-plans && pip install -e .
challenge-plans run examples/spec-sample.md --type spec --sink markdown   # verdict on the bundled sample
```

Or hand it to your coding agent — *"Install challenge-plans and run `challenge-plans doctor`"* — and it'll do the above. To use it **as an agent skill**, drop [SKILL.md](SKILL.md) where your agent discovers skills.

## Use

```bash
challenge-plans doctor                                                                 # which backends are ready
challenge-plans run path/to/spec.md --type spec --profile standard --sink markdown     # harden a plan/spec
challenge-plans run change.diff --type diff --sink markdown                             # review a git diff
challenge-plans run trip.md --type plan --sink markdown                                  # review ANY plan (a trip, a launch, a hire)
challenge-plans weigh path/to/options.yaml --profile standard --sink markdown           # vote across options
challenge-plans run path/to/spec.md --enforce                                           # CI gate: non-approve exits non-zero
challenge-plans run path/to/spec.md --type spec --sink markdown --lang zh                # findings written in Chinese
# not pip-installed? prefix with: PYTHONPATH=src python3 -m challenge_plans.cli ...
```

Ready-to-run samples live in [`examples/`](examples/) (`spec-sample.md`, `options.yaml`). `options.yaml`:
```yaml
question: Refactor auth with approach A or B?
options:
  - id: A
    text: One-shot rewrite — concentrated risk, clean result
  - id: B
    text: Incremental migration — slower, every step reversible
```

- `--profile fast|standard|deep`, `--sink stdout|markdown`, `--enforce` (non-approve verdicts exit non-zero; advisory exit 0 by default).
- `--lang <code>` writes the human-readable output in your language (default `en`) — see [below](#output-in-your-language).
- `[sev✓]` = cross-family verified, may hard-gate; `[sev?]` = unverified, advisory only.
- **Artifact types:** `--type spec`, `--type diff`, and `--type plan` are supported; `decision` is reserved (rubric pending).

The bundled [SKILL.md](SKILL.md) routes **review/QA** of a plan/spec to `run` automatically; option-voting is the `weigh` subcommand.

## Example: stress-testing a plan (not just code)

`--type plan` reviews **any** plan you're about to act on — a trip, a launch, a hire, a move — not just a dev spec. Take a rough Kyoto-trip plan ([`examples/plan-sample.md`](examples/plan-sample.md)):

```text
$ challenge-plans run examples/plan-sample.md --type plan --sink markdown

# challenge-plans · challenge · verdict: request_changes
- [high✓] Non-refundable flights locked before validating the trip  @L10  (irreversibility_or_high_cost, by claude:feasibility)
- [med ] Day 2 packs six sights across the city — likely undoable  @L4   (ignored_constraint, by gpt:risk)
- [med ] "A good trip" is never defined, so nothing can be judged  @L1   (missing_success_criteria, by claude:goal-alignment)
```

Two ideas do the work:

- **Failure types** — every objection must be tagged with one of a fixed menu of *ways a plan can break* (`missing_success_criteria`, `ignored_constraint`, `unaddressed_risk`, `dependency_or_sequencing_gap`, `unstated_assumption`, `goal_misalignment`, `irreversibility_or_high_cost`, `no_fallback`). No vague "this feels off" — each finding is concrete, anchored to a line, and dedup-able.
- **Lenses** — each reviewer wears a different hat so they don't all stare at the same spot: **feasibility** (can it actually be done under real constraints), **risk** (what's most likely to go wrong / is irreversible), **goal-alignment** (do the steps serve the stated goal; what assumptions must hold). `--profile fast` uses one lens, `standard` all three, `deep` runs multiple rounds until no *new* objection survives.

## Why a tool, and not just a prompt?

You could paste "review my plan adversarially" into any chat. The reason this is a CLI is **consistency**: a plain-prompt skill drifts between agents and runs — one does three rounds, another does one; one treats a timed-out reviewer as "no objection", another as "inconclusive"; one keeps a minority blocker, another lets the majority bury it. challenge-plans turns the review into a **repeatable protocol**: spawn the reviewers, enforce the failure-type schema, detect timeouts/missing votes, dedup by anchor, require *cross-family* reproduction before a finding can hard-gate, and resolve one 6-state verdict. Same plan in, same shape of answer out — testable and pinned by a test suite, not left to each agent's mood.

### Output in your language

challenge-plans ships an English codebase, but the reviewers can answer in **any** language — just add `--lang`:

```bash
challenge-plans run plan.md --type spec --lang zh     # objections, evidence, reproductions in Chinese
challenge-plans weigh options.yaml --lang ja          # deliberation reasons in Japanese
```

`--lang` only switches the **human-readable prose** (steelman, titles, evidence, reproductions, vote reasons). JSON keys, enum values, and `L12-15` line anchors stay verbatim, so parsing, dedup, and CI gates are unaffected. It's equivalent to exporting `CHALLENGE_PLANS_LANG` once. There's no separate translated build to maintain — the same English source localizes on demand.

**As an agent skill:** your agent just passes `--lang <your-language>` and the whole cross-review comes back localized. The bundled [SKILL.md](SKILL.md) documents the flag so the calling agent can set it from the user's language automatically.

## Two modes

challenge-plans isn't one feature — it's two modes on one engine. The **calling agent routes by intent**; the user never has to pick:

| | **challenge** (adversarial) | **weigh-options** (deliberation) |
|---|---|---|
| When | You have a **drafted** plan/spec to poke holes in / harden | You have **several options / a pile of to-dos** and aren't sure which |
| Routing signal | a single drafted artifact + "review / find flaws / can this execute" | multiple candidates + "which one / rank these / is it worth it" |
| Aggregation | **Evidence survival** — a minority can be right, **no majority vote** | **Weighted majority + exposed dissent** — only genuine trade-offs get voted on |
| Output | 6-state verdict + surviving objections + reproductions / counter-evidence | ranked options + vote tally + strongest dissent |

**The agent picks the mode — it isn't dumped on the user:** it reads the intent and routes "review a drafted artifact" to adversarial mode and "choose among options" to deliberation, with deterministic routing signals defining the boundary. During deliberation, if an option is flagged with a **mechanically verifiable blocker**, the recommendation is **downgraded to `discuss` and you're asked to verify it in challenge mode** rather than adopting it outright — so a vote can never outweigh a falsifiable minority objection.

## How it works

**Adversarial mode** (reduce-rework loop):
```
drafted artifact + bounded context
  → multiple persona/CLI challengers each steelman → find flaws (bound to specific text, no hedging)
  → Verifier (cross-family) produces a minimal reproduction / contradicting source line
  → dedup by canonical key + evidence-survival
  → single verdict pipeline → 6-state verdict + panel-integrity check
  → (--deep: multi-round to two-condition convergence)
```

**Deliberation mode** — the methodology is a strict three-phase flow. The `weigh` CLI implements phase ③ (it votes on the options you hand it); phases ①② are the calling agent's responsibility before invoking it — **no shortcuts**:
```
① align    (agent) share full background with every voter first — the question, constraints, known facts — don't pre-supply options
② collect  (agent) each voter independently, unseen by the others and not fed the orchestrator's preferences, generates candidates → dedup/cluster into an option pool
③ vote     `challenge-plans weigh` votes on that option pool (model_family-weighted to block false consensus) → ranking + tally + dissent
           hands back to a human only on a tie / missing votes; otherwise closes the loop and returns a result
```

## What it guards against — 7 multi-agent failure modes

These traps are ones a naive multi-agent setup almost always falls into — and ones **we hit ourselves while building this tool with its own adversarial process**. Each guard is built into the design, and the design is dogfooded:

1. **Vote/finding loss** — a challenger is truncated/timed-out/unparseable and the system silently aggregates a partial panel. **Guard:** machine-readable capture + per-voter integrity self-check; missing votes never approve or declare a majority.
2. **Option anchoring** — the orchestrator only offers its own pre-picked options, so agents merely ratify the framing. **Guard:** deliberation always diverges (generate first, vote second); voters aren't fed the orchestrator's preferences.
3. **Premature hand-off** — the orchestrator bounces the open decision back to the human mid-way instead of finishing the vote. **Guard:** close the loop and return a result; hand back only on a tie / missing votes.
4. **Majority over minority** — out-voting a minority that has a reproducible blocker. **Guard:** two modes with split aggregation + the escape gate; adversarial mode bans voting and lets evidence beat headcount.
5. **Single-round complacency** — one pass declared sufficient. **Guard:** `--deep` multi-round to convergence + adversarial review of the code itself before shipping.
6. **False consensus** — same-model personas counted as independent votes, so one model's bias gets cloned into a "majority". **Guard:** per-`model_family` weight cap, raw/weighted both shown, single-family warning.
7. **False convergence** — declaring "done" when no *new* objection appeared but an old blocker is still open. **Guard:** two-condition convergence (new_surviving == 0 **and** unresolved_required == 0).

## Backends

challenge-plans drives whatever subscription coding CLI you already have logged in — e.g. **Claude Code** (`claude`) or **OpenAI Codex** (`codex`). You don't need any specific one. With **two different vendors** it can cross-verify findings; with one, results stay advisory. No API keys, and no per-token API charges from this tool (`doctor` checks the CLIs are logged in, not your billing; usage still counts against your normal subscription limits).

It needs **at least one** logged-in subscription CLI to run — with none, it can't (that's the no-API-keys trade-off). Run **`challenge-plans doctor`**: it names each backend's state and the exact fix (install it, or log in), so you — or your agent — always know the next step.

## Works with your planning workflow

challenge-plans is the **"review before you execute"** step — it composes with the planning skills you may already use.

**[superpowers](https://github.com/obra/superpowers)** runs `brainstorming → writing-plans → executing-plans`. After `writing-plans` saves your plan to `docs/superpowers/plans/<date>-<feature>.md`, review it before execution:

```bash
challenge-plans run docs/superpowers/plans/<date>-<feature>.md --type spec --sink markdown
```

This slots exactly where superpowers' own pre-execution review sits — but upgrades that single-subagent check to a **multi-CLI, cross-family, vote-capable** pass. Feed surviving objections back into `writing-plans`, then run `executing-plans`. (It's an external tool — nothing auto-invokes it; you or your agent wire it into the seam, and read the *actual* saved plan path since user prefs can change it. A dedicated `--type plan` rubric is on the roadmap; `--type spec` works today.)

**[grill-me](https://github.com/mattpocock/skills)** (mattpocock/skills) is complementary and runs *earlier*: `/grill-me` interviews you one question at a time to align with the agent *while the plan is still forming* — it sharpens understanding, it doesn't emit a file. Once you've got a written plan or PRD, hand that artifact to challenge-plans. In short: **grill-me sharpens by interview (one agent, you in the loop) → challenge-plans stress-tests the draft (many agents, evidence-based)**.

**For agents:** once a plan file exists, invoke the `challenge-plans` skill on it before triggering execution, and present the surviving, cross-verified objections as your review recommendation instead of rubber-stamping the plan.

## Status

**v1 — usable.** Both modes work end-to-end, validated against a real spec and pinned by a pytest suite, hardened across multiple cross-agent adversarial-review rounds.

Known boundaries (also reflected in the run output): concern dedup is exact-anchor only; no idle-timeout (wall-clock only); deliberation blockers are flagged, not yet auto-verified by the Verifier; the open-decision divergence phase is the calling agent's job; `manual_paste`/Gemini adapters are follow-ups.

## Testing

```bash
pip install -e ".[dev]" && pytest      # pythonpath/testpaths preconfigured
```
The suite pins every invariant established across the adversarial-review rounds.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The project is dogfooded: reviewing your own change with `challenge-plans run <change>.diff --type diff` before opening a PR is encouraged.

## License

[Apache-2.0](LICENSE).
