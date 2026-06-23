# Contributing

Thanks for your interest in challenge-plans.

## Dev setup

```bash
pip install -e ".[dev]"     # installs the package + pytest
pytest                      # pythonpath/testpaths are preconfigured
challenge-plans doctor      # check your backend CLIs are logged in
```

Python ≥ 3.10. The only runtime dependency is PyYAML.

## Ground rules

- **Tests pin behavior.** Every non-trivial change should keep `pytest` green; add a test for new behavior. The suite encodes the invariants established across the project's adversarial-review rounds — don't loosen them without a reason.
- **Dogfood it.** This is an adversarial-review tool; we review our own plans and diffs with it. Running `challenge-plans run <your-change>.diff --type diff` before opening a PR is encouraged.
- **No silent simplification of guarantees.** The integrity, verification, and false-consensus guards (see README) are load-bearing; if you change one, say so explicitly in the PR.
- **Keep it backend-neutral.** The tool must work with at least one subscription CLI and degrade gracefully (advisory) when only one model family is available.

## Reporting issues

Open a GitHub issue with the command you ran, the JSON/Markdown output it printed (redact anything sensitive), and what you expected.
