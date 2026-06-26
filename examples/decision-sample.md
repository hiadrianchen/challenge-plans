# Decision: keep challenge-plans in Python (don't rewrite in TypeScript)

We decided to keep building challenge-plans in Python rather than rewriting it in TypeScript.

Context: a friend who dislikes Python said the project would feel cleaner in TS, and the Python
version situation does look messy. The tool is already shipped — v0.1.3 on PyPI, ~68 tests, an
automated OIDC publish pipeline — and it works by driving logged-in subscription CLIs as
subprocesses, which any language can do.

Reasoning for staying:
- The friend's preference is about taste; rewriting working software for taste rarely pays off.
- TypeScript would give us `npx` distribution and nicer native typing.
- We've already sunk a lot into the Python version, so switching now would waste that work.
- A rewrite is the cleanest path to a tidy codebase.

We'll revisit only if the maintainer personally loses motivation to work in Python.

<!--
Try it:  challenge-plans run examples/decision-sample.md --type decision --profile standard --sink markdown
This decision deliberately leans on a secondhand aesthetic preference as evidence, frames it as a
binary Python-vs-rewrite (ignoring the cheaper "clean up the env with uv" alternative), uses sunk
cost as a reason to stay, treats a full rewrite as the path to cleanliness without weighing its
irreversibility, and sets a vague revisit trigger — a good decision review should surface those.
-->
