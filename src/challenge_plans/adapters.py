"""Adapter layer: transport decoupling, probes, and §9a integrity capture.

v0 implements ClaudeAdapter over CLI transport (subscription-based) plus MockAdapter
for structural tests without real model calls. codex/manual_paste/browser are planned
as later increments.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum

from .prompts import END_MARKER
from .schema import CaptureFailureReason


class ProbeState(str, Enum):
    READY = "ready"
    NOT_LOGGED_IN = "not_logged_in"
    INTERACTIVE_ONLY = "interactive_only"
    BILLING_UNKNOWN = "billing_unknown"
    UNSUPPORTED_VERSION = "unsupported_version"
    NOT_INSTALLED = "not_installed"


@dataclass
class CaptureResult:
    ok: bool
    text: str = ""
    reason: CaptureFailureReason | None = None


@dataclass
class VoterSpec:
    voter_id: str
    backend: str
    model_family: str
    role: str = "challenger"
    transport: str = "cli"
    persona: str = "execution-failure"
    model: str | None = None
    effort: str | None = None


def strip_marker(text: str) -> str:
    """Strip the trailing END_MARKER line after check_capture has confirmed it is line-exclusive."""
    lines = text.rstrip().splitlines()
    if lines and lines[-1].strip() == END_MARKER:
        return "\n".join(lines[:-1])
    return text


def check_capture(text: str, returncode: int) -> CaptureResult:
    """§9a integrity check: non-empty and END_MARKER must be the final non-empty line by itself.

    Substring matching can be fooled when the model writes the marker inside a JSON string
    or echoes the prompt, so the final line must exactly equal the marker.
    """
    if returncode != 0:
        return CaptureResult(False, text, CaptureFailureReason.EXIT_NONZERO)
    if not text.strip():
        return CaptureResult(False, text, CaptureFailureReason.EMPTY)
    lines = text.rstrip().splitlines()
    if not lines or lines[-1].strip() != END_MARKER:
        return CaptureResult(False, text, CaptureFailureReason.TRUNCATED)
    return CaptureResult(True, text, None)


class ClaudeAdapter:
    """transport=cli, using local `claude -p` subscription quota rather than per-token billing."""

    backend = "claude-cli"
    model_family = "claude"

    def available(self) -> bool:
        # Cheap discovery during run: include it optimistically if installed; login failures
        # are converted to capture_failed by §9a during invoke.
        return shutil.which("claude") is not None

    def probe(self) -> ProbeState:
        if not shutil.which("claude"):
            return ProbeState.NOT_INSTALLED
        # Real auth probe: --version also returns 0 when logged out, so run one minimal `claude -p`.
        try:
            r = subprocess.run(["claude", "-p", "--output-format", "text", "ok"],
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return ProbeState.BILLING_UNKNOWN
        except OSError:
            return ProbeState.NOT_INSTALLED
        out = (r.stdout + r.stderr).lower()
        if r.returncode != 0 or "not logged in" in out or "/login" in out:
            return ProbeState.NOT_LOGGED_IN
        return ProbeState.READY if r.stdout.strip() else ProbeState.BILLING_UNKNOWN

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 150) -> CaptureResult:
        """v0: total subprocess wall-clock timeout, not the §9 idle timeout.

        Slow calls that still emit output can be killed; idle-timeout remains a known v0 gap
        Capture all stdout instead of tailing or truncating the stream.
        """
        cmd = ["claude", "-p", "--output-format", "text", prompt]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_timeout)
        except subprocess.TimeoutExpired:
            return CaptureResult(False, "", CaptureFailureReason.TIMEOUT)
        except OSError:
            return CaptureResult(False, "", CaptureFailureReason.EXIT_NONZERO)
        return check_capture(r.stdout, r.returncode)


class CodexAdapter:
    """transport=cli, using local `codex exec` (ChatGPT subscription) as the GPT-family peer."""

    backend = "codex-cli"
    model_family = "gpt"

    def available(self) -> bool:
        if not shutil.which("codex"):
            return False
        try:  # codex login status is quick enough for cheap login checks during run.
            r = subprocess.run(["codex", "login", "status"], capture_output=True,
                               text=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            return False
        return "logged in" in (r.stdout + r.stderr).lower()

    def probe(self) -> ProbeState:
        if not shutil.which("codex"):
            return ProbeState.NOT_INSTALLED
        return ProbeState.READY if self.available() else ProbeState.NOT_LOGGED_IN

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 300) -> CaptureResult:
        # -o writes the machine-readable final message to a file for correct §9a capture,
        # without tail truncation.
        # Medium reasoning balances speed and quality; high often exceeded 240s in practice,
        # degrading runs to a single model family.
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
               "-c", "model_reasoning_effort=medium", "-o", path, prompt]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_timeout)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                text = ""
            # If the -o file is empty, fall back to stdout; some Codex forms print the final
            # answer there instead. The fallback still goes through §9a integrity checks and
            # must include the marker as the final line.
            if not text.strip():
                text = r.stdout
            return check_capture(text, 0 if text.strip() else r.returncode)
        except subprocess.TimeoutExpired:
            return CaptureResult(False, "", CaptureFailureReason.TIMEOUT)
        except OSError:
            return CaptureResult(False, "", CaptureFailureReason.EXIT_NONZERO)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class MockAdapter:
    """Structural-test adapter: return scripted output by voter_id without real model calls."""

    backend = "mock"
    model_family = "mock"

    def __init__(self, scripted: dict[str, str], model_family: str = "mock"):
        self._scripted = scripted
        self.model_family = model_family

    def available(self) -> bool:
        return True

    def probe(self) -> ProbeState:
        return ProbeState.READY

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 150) -> CaptureResult:
        return check_capture(self._scripted.get(spec.voter_id, ""), 0)
