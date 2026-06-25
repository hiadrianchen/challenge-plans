# Design draft: mechanical verification for `--type diff`

Status: **design ready — awaiting owner decision (not implemented).**

## Goal
Let a code finding hard-gate on a *mechanically-run* check (tests / typecheck / lint / static analysis), not only on a second LLM agreeing. Today the `✓` on a `--type diff` finding is **cross-model confirmation** (another model family reproduced it with a line anchor) — it never runs your code. For a real CI gate on code, that is too weak.

## The constraint that shapes everything
challenge-plans reviews a **diff file**. It does not, by itself, have the repository, dependencies, or environment needed to run tests. And the artifact under review is **untrusted input** — so the tool must never auto-execute commands derived from the diff. Any "run a check" must be an **explicit, user-configured command run against the user's own repo**, never auto-detected-and-run on untrusted content.

## Options
- **A. Explicit `--verify "CMD"` (opt-in).** The user passes a command (e.g. `--verify "pytest -q"`). The tool runs it in the current working directory; a non-zero exit injects a `mechanically_verified` critical concern carrying the command + captured output as evidence; a clean exit is recorded as a passing mechanical check. No auto-detection. **Recommended.**
- **B. Auto-detect + run** (`pyproject`→pytest, `package.json`→npm test). Convenient but runs commands the user didn't type, on a tool whose artifact is untrusted — unsafe. **Rejected.**
- **C. Pluggable verifier interface** with built-in presets (pytest/tsc/ruff). More powerful, but bigger surface; the preset still ultimately runs a command, so it's A with sugar. Defer to a follow-up.
- **D. Consume-only**: the tool never runs anything; the *caller* runs tests and feeds results in via an input file/flag. Safest, but pushes all the work to the caller. Good as a complement to A, not a replacement.

> **Scope correction (from self-review):** a global `--verify "pytest"` pass/fail is a *project-level gate* ("do the tests pass"), **not** mechanical verification of a *specific finding*. Those are two different features. v1 should ship the project-level gate, clearly labeled as such, and treat true per-finding mechanical verification (generate/run a targeted repro per finding) as a separate, much larger future item.

## Recommended design
1. **`--verify "CMD"`** (opt-in, explicit). Run `CMD` in cwd with a timeout. Record the result as a **top-level `project_checks` entry** in the manifest — `{cmd, status, output_tail}` with `status ∈ {passed, failed, errored, timed_out}` — **not** as an injected "`mechanically_verified` finding". (Per Codex second-opinion: injecting it as a finding would again imply a *specific LLM finding* was test-reproduced, which it wasn't. The check proves "the workspace is/ isn't green", a project-level fact.) A `failed` check hard-gates the verdict; `errored`/`timed_out` are surfaced but advisory (you can't tell a real failure from a broken environment).
2. **Schema split.** Introduce `verification.method ∈ {cross_model_confirmed, mechanically_verified}`. The LLM Verifier sets `cross_model_confirmed` (today's `✓`); `--verify` sets `mechanically_verified`. Output keeps `✓` but distinguishes the two in detail. (Addresses the review's "don't call an LLM check `verified`".)
3. **Safety:** never auto-detect or auto-run; `--verify` is the only path, and it runs the user's own command in the user's repo — the diff content never becomes a command.

## Open decisions (owner)
1. **Auto-run vs explicit only** — recommend explicit `--verify CMD` only (safety). Confirm.
2. **Failing `--verify` ⇒ hard-gate always, or advisory?** — recommend hard-gate (a failing test is the strongest evidence we can get).
3. **Rename schema `verified` → `cross_model_confirmed` + add `mechanically_verified`?** — recommend yes; small breaking change to the manifest field.
4. **Built-in presets now (pytest/tsc/ruff) or just generic `CMD`?** — recommend generic `CMD` first, presets later.
5. **Timeout / output-capture limits for `--verify`?**

## Risks
- Running a user command is still arbitrary code execution **the user opted into** — document that `--verify` runs in their shell/repo, not in a sandbox.
- Manifest schema change (`verification.method`) is mildly breaking for anyone parsing the JSON.

## Non-goals
- No sandbox/container execution (out of scope for v1).
- No auto-detection of project type.

## Self-review findings (challenge-plans `--type plan`, folded in)
Adversarial review of this draft surfaced these — they become owner decisions / v1 constraints:

1. **Global pass/fail ≠ per-finding verification (high✓, ×2).** A failing suite doesn't prove *this specific finding* is real. Resolution: v1 `--verify` is a **project gate**, labeled as such; per-finding mechanical verification is a separate future item. (Scope correction above.)
2. **No fallback for environmental/flaky failure (high✓).** A missing dependency, flaky test, or infra error would always hard-gate. Resolution: distinguish "the command itself failed to run" from "a real test failed"; offer an advisory mode and surface the captured output so a human can tell which it is.
3. **Non-zero exit ≠ real test failure (high✓ / medium).** Exit codes also mean usage errors, crashes, missing deps. Resolution: don't claim `mechanically_verified` on any non-zero — only on a clean *failure signal* we can identify; otherwise mark the run "verify_errored", not "verified".
4. **Shell vs argv execution unspecified (high✓).** `--verify "CMD"` shell semantics need defining (shell string vs argv list; quoting; the user owns the command). Resolution: decide and document; default to running via the user's shell, explicitly opt-in.
5. **Timeout + output-capture limits undecided but required (medium, ×3).** Must specify a wall-clock timeout and a captured-output cap before building.
6. **Severity assumption (medium).** "Any verify failure ⇒ critical" is a choice; make severity configurable or justify the default.
