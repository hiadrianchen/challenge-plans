"""challenge-plans — multi-agent adversarial review & deliberation for plans/specs.

Runs on the subscription CLIs already logged in on your machine (Claude Code, Codex),
hardening a plan/spec before execution to reduce rework. Two modes: `challenge`
(adversarial, evidence-survival) and `weigh-options` (deliberation, weighted voting).

See README.md for usage and the design overview.
"""
from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the installed package metadata (from pyproject) — never drifts.
    __version__ = version("challenge-plans")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.2.0"
