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

Honest about what isn't built yet. challenge-plans is **advisory-grade** today — great for a human/agent review pass, not yet a hard CI quality gate. Planned, roughly in order:

- **`--strict` gate mode** — let `discuss` (and optionally `approve_with_unverified_timeouts`) exit non-zero, so a single-family run can't look gated while passing. Today `--enforce` exits non-zero only on `request_changes` / `inconclusive` / `schema_invalid`.
- **Mechanical verification for `--type diff`** — run tests / typecheck / lint / static analysis (not just a second LLM) before a code finding can hard-gate. Today the `✓` is cross-model confirmation, not a test run.
- **Persistent run provenance** — write raw outputs, model + version, artifact hash, and verdict to a store for audit and replay.
- **Robust source anchors** — block id / content hash / git hunk range instead of bare line numbers, so findings survive edits to long-lived artifacts.
- **Untrusted-artifact isolation** — prompt-injection hardening (the artifact is untrusted input) + schema-repair retries on malformed output.
- **Backend provider abstraction** — CLI transport today; SDK / API / `manual_paste` planned, each declaring data-egress, quota, and timeout policy.

These came out of adversarial review of challenge-plans itself — fittingly.
