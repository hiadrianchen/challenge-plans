# How challenge-plans works

The deep dive. For the quick pitch and install, see the [README](../README.md).

## Two modes on one engine

The calling agent routes by intent; you never have to pick.

| | **challenge** (adversarial) | **weigh** (deliberation) |
|---|---|---|
| When | You have a **drafted** plan / spec / diff to poke holes in | You have **several options** and aren't sure which |
| Routing signal | one drafted artifact + "review / find flaws / can this run" | multiple candidates + "which one / rank these / worth it" |
| Aggregation | **evidence survival** — a minority can be right, **no majority vote** | **weighted majority + exposed dissent** — only genuine trade-offs get voted on |
| Output | 6-state verdict + surviving objections + reproductions | ranked options + vote tally + strongest dissent |

If a deliberation option carries a **mechanically verifiable blocker**, the recommendation is downgraded to `discuss` and you're sent to verify it in challenge mode — so a vote can never bury a falsifiable minority objection.

## Adversarial review (the reduce-rework loop)

```
drafted artifact (plan / spec / diff / any plan) + bounded context
  → multiple persona/CLI challengers each steelman → find flaws (bound to specific text, no hedging)
  → Verifier (cross-family) produces a minimal reproduction / contradicting source line
  → dedup by canonical key + evidence-survival
  → single verdict pipeline → 6-state verdict + panel-integrity check
  → (--deep: loop the panel — each round is shown prior findings and hunts new ones — until a round adds nothing new, or the round cap)
```

**Cross-family verification** is the core guarantee: a high/critical objection only earns hard-gate authority (`✓`) when an *independent model family* reproduces it with concrete, line-anchored evidence. This is **cross-model confirmation, not a mechanically-run test** — another family says "yes, here's the line"; nothing runs your code. (For `--type diff`, wiring in real test/typecheck/lint verification is on the Roadmap.) A single model's claim stays advisory (`?`). That's why bringing two different vendors (e.g. Claude Code + Codex) matters — they check each other.

## Deliberation (a strict three-phase flow)

The `weigh` CLI implements phase ③; phases ①② are the calling agent's job before invoking it — **no shortcuts**:

```
① align    (agent) share full background with every voter first — the question, constraints, known facts — don't pre-supply options
② collect  (agent) each voter independently, unseen by the others and not fed the orchestrator's preferences, generates candidates → dedup/cluster into an option pool
③ vote     `challenge-plans weigh` votes on that pool (model_family-weighted to block false consensus) → ranking + tally + dissent
           hands back to a human only on a tie / missing votes; otherwise closes the loop
```

## The 7 multi-agent failure modes it guards against

Traps a naive multi-agent setup almost always falls into — and ones **we hit ourselves while building this tool with its own adversarial process**. Each guard is enforced in code.

1. **Vote/finding loss** — a challenger is truncated/timed-out/unparseable and the system silently aggregates a partial panel. **Guard (in code):** machine-readable capture + per-voter integrity self-check; missing votes never approve or declare a majority.
2. **Option anchoring** — the orchestrator only offers its own pre-picked options. **Guard (in code):** deliberation always diverges (generate first, vote second); voters aren't fed the orchestrator's preferences.
3. **Premature hand-off** — the orchestrator bounces the decision back to the human mid-way. **Guard (in code):** close the loop and return a result; hand back only on a tie / missing votes.
4. **Majority over minority** — out-voting a minority that has a reproducible blocker. **Guard (in code):** two modes with split aggregation + the escape gate; adversarial mode bans voting and lets evidence beat headcount.
5. **Single-round complacency** — one pass declared sufficient. **Guard (in code):** `--deep` loops the panel, each round hunting what the last missed, until a round finds nothing new.
6. **False consensus** — same-model personas counted as independent votes. **Guard (in code):** per-`model_family` weight cap, raw/weighted both shown, single-family warning.
7. **False convergence** — declaring "done" when a round found nothing new. **Guard (in code):** `--deep` stops only when a round surfaces zero new concerns (`convergence.reason = no_new_objections`); otherwise it reports `round_cap_reached`, never a false "done".

## Why a tool, and not a prompt / skill.md / MCP

"Adversarial review" as a concept is one prompt away: a `skill.md` or an MCP that says *"review this and list the problems"* gets you a single model narrating worries in prose. That form **structurally cannot** do the things that make the output trustworthy — each of these is a control-flow guarantee, not a wording you can add to a prompt:

- **Independence.** In a prompt the same model both *raises* and *judges* the objection — correlated blind spots sail through. Here a **different vendor's** model must reproduce a high/critical finding with a line anchor before it counts (`verifier.py` + `adapters.py`). Same-family "yes I agree" is explicitly downgraded.
- **A verdict you can gate on.** Free-text "this seems risky" ×3 from one model isn't three problems and can't block CI. `canonical_key` dedups findings by a mechanical fingerprint, and `resolve_verdict` turns the surviving evidence into one of 6 states **in code — the model never emits the verdict**.
- **No silent passes.** A truncated or timed-out model in a prompt just *looks* like "no objections found." The capture-integrity + panel checks catch the missing voter, and an incomplete panel can never read as `approve`.
- **Evidence over headcount.** You can *ask* a prompt not to out-vote a minority that has a reproducible blocker; you can't *enforce* it. The split-aggregation pipeline does, in control flow (adversarial mode bans voting entirely).
- **Rides your subscription.** An MCP/API wrapper bills per token. The CLI-subprocess transport drives your already-logged-in Claude/Codex quota instead, and strips `ANTHROPIC_*` so it can't silently fall back to a metered API key.

In one line: **the prompts produce evidence; the Python produces the verdict.** That boundary — models are witnesses, code is the judge — is the whole tool.

## What each part does (the module map)

Nine small modules under `src/challenge_plans/`, each owning one guarantee above:

| Module | Job | Why it exists (what a naive form gets wrong) |
|---|---|---|
| `schema.py` | Core data model + the **single verdict pipeline**. `canonical_key()` fingerprints each concern (anchor + failure_type + violated field + …); `resolve_verdict()` derives the 6-state verdict mechanically. | The one piece a prompt can't be: the verdict is computed from evidence, **not** asserted by a model. Free-text identity is banned so findings dedup and can't be gamed by re-wording. |
| `adapters.py` | Transport. One fresh `claude -p` / `codex exec` subprocess per call; strips `ANTHROPIC_*` to force subscription auth; capture-integrity check (`END_MARKER` must be the final line). | Makes a truncated/timed-out reply *detectable* instead of silently trusted; keeps it on your subscription, off per-token billing. |
| `rubric.py` | Per-artifact-type registry: the `failure_type` enum + review personas + fast/standard/deep profile. | Challengers must pick a failure type from a fixed menu → findings are specific and dedup-able, not prose mush. Different lenses widen coverage on one subscription. |
| `prompts.py` | The challenger prompt: steelman-first, bind every finding to a line anchor, no hedging + `UNTRUSTED_GUARD` (treat the artifact as untrusted data) + the `END_MARKER` sentinel. | Structures the model's output so it's parseable and integrity-checkable, and defends against injection from the reviewed text. |
| `engine.py` | The orchestrator: fan out personas × adapters in parallel (capped), parse, dedup by canonical key, run the `--deep` multi-round loop + convergence, panel-integrity, call the Verifier, run `--verify` project checks, assemble the manifest. | Turns many independent model calls into one coherent, convergent, integrity-checked result. |
| `verifier.py` | The **cross-family Verifier**: for each high/critical concern, pick an adapter from a *different* model family to reproduce it; only a cross-family repro with a line anchor sets `severity_verified`. | The anti-echo-chamber core — one vendor can't both find and bless its own objection. |
| `deliberation.py` | `weigh` mode: weighted Borda with a per-`model_family` weight cap, the blocker escape gate, exposed strongest-dissent. | Blocks false consensus (same model counted as many votes) and stops a vote from burying a falsifiable minority. |
| `preflight.py` | Frontmatter/field grading: invalid `artifact_type` → `schema_invalid` (no model run wasted); a missing required field → a synthetic contract-violation concern. | Cheap mechanical gates run *before* spending model calls, and flow through the same verdict pipeline. |
| `cli.py` | Entrypoint (`run` / `weigh` / `doctor`), exit-code policy (`--enforce` / `--strict` for CI), markdown rendering, `--save` provenance. | The surface an agent or CI actually calls; the exit-code contract is what makes it a *gate*, not just a report. |

## Fits into your planning workflow

challenge-plans is the **"review before you execute"** step — it composes with planning skills you may already use.

**[superpowers](https://github.com/obra/superpowers)** runs `brainstorming → writing-plans → executing-plans`. After `writing-plans` saves your plan to `docs/superpowers/plans/<date>-<feature>.md`, review it before execution:

```bash
challenge-plans run docs/superpowers/plans/<date>-<feature>.md --type plan --sink markdown
```

This slots exactly where superpowers' own pre-execution review sits — but upgrades that single-subagent check to a **multi-CLI, cross-family, vote-capable** pass. Feed surviving objections back into `writing-plans`, then run `executing-plans`. (Nothing auto-invokes it; you or your agent wire it into the seam, and read the *actual* saved plan path since user prefs can change it.)

**[grill-me](https://github.com/mattpocock/skills)** (mattpocock/skills) is complementary and runs *earlier*: `/grill-me` interviews you one question at a time to align with the agent *while the plan is still forming* — it sharpens understanding, it doesn't emit a file. Once you have a written plan or PRD, hand that artifact to challenge-plans. In short: **grill-me sharpens by interview (one agent, you in the loop) → challenge-plans stress-tests the draft (many agents, evidence-based)**.

## Verdict states

`schema_invalid` · `request_changes` · `inconclusive` · `discuss` · `approve_with_unverified_timeouts` · `approve`. One pipeline resolves them; an incomplete panel never masquerades as `approve`.

## Known boundaries

Concern dedup is exact-anchor only; no idle-timeout (wall-clock only); deliberation blockers are flagged, not yet auto-verified by the Verifier; the open-decision divergence phase is the calling agent's job; `manual_paste` / additional adapters are follow-ups.

## Roadmap

Honest about what isn't built yet. By default challenge-plans is **advisory** (a human/agent review pass); `--strict` turns it into a hard gate, but the gate's strength is still LLM cross-model confirmation, not mechanical proof. Planned, roughly in order:

- **Mechanical verification for `--type diff`** — run tests / typecheck / lint / static analysis (not just a second LLM) before a code finding can hard-gate. Today the `✓` is cross-model confirmation, not a test run.
- **Robust source anchors** — block id / content hash / git hunk range instead of bare line numbers, so findings survive edits to long-lived artifacts.
- **Injection detection** — the artifact is already framed as untrusted input (every reviewer is told to treat the delimited content as data, ignore instructions embedded in it, and flag manipulation attempts), and a malformed challenger reply now gets one schema-repair retry before the voter is dropped. Still planned: a dedicated injection detector.
- **Backend provider abstraction** — CLI transport today; SDK / API / `manual_paste` planned, each declaring data-egress, quota, and timeout policy.

These came out of adversarial review of challenge-plans itself — fittingly.
