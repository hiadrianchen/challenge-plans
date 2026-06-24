# Design draft: robust source anchors

Status: **design ready — awaiting owner decision (not implemented).**

## Goal
Make a finding's anchor survive edits to the artifact. Today a concern binds to a bare line range (`L12-15`), validated by `_valid_span`, and `canonical_key` derives identity from `artifact_span + failure_type`. Line numbers drift the moment the document changes, so a finding can't be correlated across versions of an evolving artifact.

## When this actually matters (be honest)
Line anchors are **fine for a one-shot review** — the artifact doesn't change mid-run. Robust anchors only pay off when the tool **re-reviews an evolving artifact over time** and needs to say "this is the same finding as last version." That re-review feature **does not exist yet**. So #15's real priority is gated on whether long-lived / repeated-review tracking is a roadmap direction. If it's not, this stays a nice-to-have.

## Options
- **A. Line range + content hash.** Keep `L12-15` but also record a hash of the anchored text. On re-review, if lines moved, the hash relocates them. Cheapest; the engine can compute the hash from the artifact itself (doesn't trust the model). Survives reordering, not edits to the content.
- **B. Markdown heading path.** For structured docs: anchor to `# A > ## B` instead of a line. Survives line shifts within a section; needs an AST/heading parser; only applies to markdown-ish artifacts.
- **C. git blob hash + hunk.** For `--type diff` / code in git: anchor to blob hash + hunk range. Precise for code under git; needs git context the tool doesn't currently have.
- **D. Byte range.** More fragile than lines — rejected.

## Recommended design
- **Per-artifact-type anchor strategy**, not one scheme for all: `diff` → line + content hash (and git hunk once git context exists); markdown `plan`/`spec` → line + content hash (+ heading path later); default → line + content hash.
- **Phase 1 (incremental, low risk):** add a `content_hash` alongside the existing line span — the engine computes it from the anchored lines. It is **relocation metadata only** (find unchanged content that *moved*); it is **NOT** part of `canonical_key`, because a content hash changes the moment the content is edited — putting it in the identity key would give an edited-but-same finding a brand-new identity, the opposite of the stability goal. Existing line-anchor behavior unchanged; the hash is purely additive. **Caveat:** content_hash survives *reordering*, not *edits to the content itself*; surviving real edits needs fuzzy/semantic relocation (out of scope).
- **Phase 2:** heading-path (markdown) and git-hunk (diff) anchors, behind the per-type strategy.

## Impact on existing code
- `canonical_key` (in `schema.py`) — if identity starts using `content_hash`, the **dedup key changes**, which changes which concerns merge. Must be deliberate + versioned.
- `_valid_span` (in `engine.py`) — currently regex-validates `L<n>-<n>` within line count. Each new anchor type needs its own validator; keep line validation as the default.
- Manifest schema — adds `anchor: {type, value, content_hash}`; mildly breaking for JSON consumers.

## Migration cost
- Phase 1 is additive (new field, optional key change) — low.
- Changing `canonical_key` semantics affects dedup and any pinned tests; needs a version bump + test updates.
- Phase 2 (parsers for heading path / git hunk) is the larger cost.

## Open decisions (owner)
1. **Is re-review of evolving artifacts on the roadmap?** If no, deprioritize #15. (Gates everything below.)
2. **Phase 1 only (line + content hash) for now?** — recommended.
3. **Does `canonical_key` adopt `content_hash`** (changes dedup identity, mildly breaking) or keep line-based key + carry hash as metadata only?
4. **Per-type strategy** vs one scheme — recommend per-type.
5. Which types get git-hunk / heading-path anchors, and when.

## Non-goals
- No full AST tracking / semantic anchoring in v1.
- No change to the one-shot review path's behavior (line anchors stay the default).

## Self-review findings (challenge-plans `--type plan`, folded in)
Adversarial review of this draft caught real conceptual errors — corrected above:

1. **content_hash doesn't survive *edits*, only *reordering* (high✓, ×2).** The goal said "survive edits"; a hash of the text changes when the text is edited. Phase 1's value is narrower than first stated — relocating unchanged content that moved. True edit-survival needs fuzzy/semantic matching (out of scope).
2. **Putting content_hash in `canonical_key` inverts identity stability (high✓).** An edit would change the key, so the *same* finding would get a *new* identity — the opposite of the goal. Corrected: content_hash is metadata only; identity must come from something stable (structural anchor / failure_type), never the content hash.
3. **Building anchor identity before its consumer exists (medium).** Re-review of evolving artifacts isn't a feature yet, so robust-anchor identity is premature — confirms the "when this matters" gate at the top. Recommend deferring until that consumer is on the roadmap.
4. **Schema/`canonical_key` change needs a compatibility + versioning plan (medium).** Any identity-key change is silently history-altering; version it and update pinned tests deliberately.
