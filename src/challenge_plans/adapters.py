"""Adapter layer: transport decoupling, probes, and integrity capture.

v0 implements ClaudeAdapter over CLI transport (subscription-based) plus MockAdapter
for structural tests without real model calls. codex/manual_paste/browser are planned
as later increments.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum

from .prompts import END_MARKER
from .schema import CaptureFailureReason

# Defensive ceiling on concurrent subprocesses. The panel is normally tiny (a few personas),
# but cap it so an oversized persona list can't fan out into a thread/subprocess storm.
MAX_PARALLEL_VOTERS = 8

# BYO-backend env namespace: CP_BYO_<n>_BASE_URL / _FAMILY / _TOKEN (+ optional _MODEL).
_BYO_PREFIX = "CP_BYO_"
_BYO_INDEX_RE = re.compile(r"^CP_BYO_(\d+)_")


class ProbeState(str, Enum):
    READY = "ready"
    NOT_LOGGED_IN = "not_logged_in"
    INTERACTIVE_ONLY = "interactive_only"
    BILLING_UNKNOWN = "billing_unknown"
    UNSUPPORTED_VERSION = "unsupported_version"
    NOT_INSTALLED = "not_installed"
    # Installed and logged in, but the CLI is pointed at a provider we cannot tie to the vendor
    # whose family this adapter claims. Distinct from NOT_LOGGED_IN so a withheld family is
    # explained rather than merely absent (only multi-provider CLIs like kimi can reach this).
    FAMILY_UNVERIFIED = "family_unverified"


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
    # "builtin" = the family is structurally true (distinct vendor CLI + subscription).
    # "user_declared" = BYO backend; the family is whatever the user typed, unverified.
    family_source: str = "builtin"


def claude_cli_env() -> dict[str, str]:
    """Use Claude Code's logged-in CLI auth, not inherited Anthropic API env.

    Also strips every CP_BYO_* var: the default claude adapter must never see BYO endpoint
    config, or a subscription-authenticated call could be redirected to a third-party
    endpoint (irrevocable credential leak). BYO subprocess env is built separately and
    independently in ByoAdapter._cli_env().
    """
    return {k: v for k, v in os.environ.items()
            if not k.startswith("ANTHROPIC_") and not k.startswith(_BYO_PREFIX)}


def strip_marker(text: str) -> str:
    """Strip the trailing END_MARKER line after check_capture has confirmed it is line-exclusive."""
    lines = text.rstrip().splitlines()
    if lines and lines[-1].strip() == END_MARKER:
        return "\n".join(lines[:-1])
    return text


def check_capture(text: str, returncode: int) -> CaptureResult:
    """Integrity check: non-empty and END_MARKER must be the final non-empty line by itself.

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
    family_source = "builtin"
    product = "Claude Code (Claude subscription)"
    install_hint = "install Claude Code: https://docs.claude.com/en/docs/claude-code"
    login_hint = "run `claude`, then `/login` (needs a Claude Pro/Max subscription)"

    def _cli_env(self) -> dict[str, str]:
        # Overridden by ByoAdapter; the default subscription path stays on claude_cli_env()'s
        # mandatory ANTHROPIC_*/CP_BYO_* stripping and must not weaken it.
        return claude_cli_env()

    def available(self) -> bool:
        # Cheap discovery during run: include it optimistically if installed; login failures
        # are converted to capture_failed by the integrity check during invoke.
        return shutil.which("claude") is not None

    def probe(self) -> ProbeState:
        if not shutil.which("claude"):
            return ProbeState.NOT_INSTALLED
        # Real auth probe: --version also returns 0 when logged out, so run one minimal `claude -p`.
        try:
            r = subprocess.run(["claude", "-p", "--output-format", "text", "ok"],
                               capture_output=True, text=True, timeout=60,
                               env=self._cli_env())
        except subprocess.TimeoutExpired:
            return ProbeState.BILLING_UNKNOWN
        except OSError:
            return ProbeState.NOT_INSTALLED
        out = (r.stdout + r.stderr).lower()
        if r.returncode != 0 or "not logged in" in out or "/login" in out:
            return ProbeState.NOT_LOGGED_IN
        return ProbeState.READY if r.stdout.strip() else ProbeState.BILLING_UNKNOWN

    def version(self) -> str | None:
        """Best-effort CLI version string for provenance/replay; None if unavailable."""
        if not shutil.which("claude"):
            return None
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                               timeout=20, env=self._cli_env())
        except (subprocess.TimeoutExpired, OSError):
            return None
        return r.stdout.strip() or None

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 150) -> CaptureResult:
        """v0: total subprocess wall-clock timeout, not an idle timeout.

        Slow calls that still emit output can be killed; idle-timeout remains a known v0 gap
        Capture all stdout instead of tailing or truncating the stream.
        """
        cmd = ["claude", "-p", "--output-format", "text", prompt]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_timeout,
                               env=self._cli_env())
        except subprocess.TimeoutExpired:
            return CaptureResult(False, "", CaptureFailureReason.TIMEOUT)
        except OSError:
            return CaptureResult(False, "", CaptureFailureReason.EXIT_NONZERO)
        return check_capture(r.stdout, r.returncode)


class ByoAdapter(ClaudeAdapter):
    """BYO backend: `claude -p` pointed at a user-supplied Anthropic-compatible endpoint.

    Configured purely from env (`CP_BYO_<n>_BASE_URL/_FAMILY/_TOKEN`, optional `_MODEL`) — the
    standard way third-party providers (GLM/Kimi/DeepSeek...) expose Anthropic-compatible APIs
    to the claude CLI. The built-in claude/codex adapters are untouched by this class.

    Honesty boundary: `model_family` here is whatever the user declared — the tool cannot verify
    what actually serves the endpoint, so it is plumbed through as family_source="user_declared"
    and must never be presented as the built-in cross-family guarantee.

    Token hygiene: the token lives only on this instance and in the env of THIS adapter's own
    subprocesses. It must never reach logs, diagnostics, manifests, or provenance records.
    """

    family_source = "user_declared"
    install_hint = "BYO backends drive the claude CLI binary; " + ClaudeAdapter.install_hint
    update_hint = ""

    def __init__(self, index: int, *, base_url: str, family: str, token: str,
                 model: str | None = None):
        self.backend = f"byo-cli-{index}"
        self.model_family = family
        self.product = f"BYO backend #{index} (declared family: {family}, via claude CLI)"
        self.login_hint = (f"check CP_BYO_{index}_TOKEN and CP_BYO_{index}_BASE_URL "
                           "(endpoint rejected the request)")
        self._base_url = base_url
        self._token = token
        self._model = model

    def _cli_env(self) -> dict[str, str]:
        # Independent isolation: start from an env with ANTHROPIC_* and ALL CP_BYO_* stripped,
        # then inject only this backend's endpoint + token — so backend 1's subprocess can never
        # see backend 2's token, and the raw CP_BYO_* namespace never propagates.
        env = claude_cli_env()
        env["ANTHROPIC_BASE_URL"] = self._base_url
        env["ANTHROPIC_AUTH_TOKEN"] = self._token
        if self._model:
            env["ANTHROPIC_MODEL"] = self._model
        return env


def discover_byo_adapters() -> tuple[list[ByoAdapter], list[str]]:
    """Scan env for CP_BYO_<n>_* backends -> (adapters, problems).

    A backend needs BASE_URL + FAMILY + TOKEN (all non-empty); anything incomplete is skipped
    and reported as a problem string. Problem strings name env VARIABLES only — never their
    values (a BASE_URL can embed a key, a TOKEN is one).
    """
    indices = sorted({int(m.group(1)) for k in os.environ
                      if (m := _BYO_INDEX_RE.match(k))})
    adapters, problems = [], []
    for n in indices:
        base_url = os.environ.get(f"CP_BYO_{n}_BASE_URL", "").strip()
        family = os.environ.get(f"CP_BYO_{n}_FAMILY", "").strip().lower()
        token = os.environ.get(f"CP_BYO_{n}_TOKEN", "").strip()
        model = os.environ.get(f"CP_BYO_{n}_MODEL", "").strip() or None
        missing = [f"CP_BYO_{n}_{name}" for name, v in
                   (("BASE_URL", base_url), ("FAMILY", family), ("TOKEN", token)) if not v]
        if missing:
            problems.append(f"byo backend #{n} incomplete — missing " + ", ".join(missing)
                            + " (a missing TOKEN could otherwise fall back to subscription "
                              "auth against a third-party endpoint)")
            continue
        adapters.append(ByoAdapter(n, base_url=base_url, family=family, token=token, model=model))
    return adapters, problems


class CodexAdapter:
    """transport=cli, using local `codex exec` (ChatGPT subscription) as the GPT-family peer."""

    backend = "codex-cli"
    model_family = "gpt"
    family_source = "builtin"
    product = "OpenAI Codex CLI (ChatGPT subscription)"
    install_hint = "install Codex CLI: https://github.com/openai/codex"
    login_hint = "run `codex` and sign in with your ChatGPT account"
    update_hint = "update Codex CLI: npm i -g @openai/codex@latest"
    # Signature of the server-side "your CLI is too old for the assigned model" rejection.
    # Real repro: HTTP 400 invalid_request_error "The '<model>' model requires a newer version
    # of Codex" — the model is chosen server-side, so only a real exec (not `login status`) sees it.
    _too_old_marker = "requires a newer version"

    def available(self) -> bool:
        if not shutil.which("codex"):
            return False
        try:  # codex login status is quick enough for cheap login checks during run.
            r = subprocess.run(["codex", "login", "status"], capture_output=True,
                               text=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            return False
        return "logged in" in (r.stdout + r.stderr).lower()

    def _probe_exec(self, timeout: int = 90) -> tuple[bool, str]:
        """One real minimal `codex exec` mirroring invoke()'s flags, for the doctor deep probe.

        `codex login status` can't see a server-side 400 that rejects an out-of-date CLI (the
        model is assigned server-side), so telling ready from too-old needs a true exec, the way
        ClaudeAdapter already sends a minimal `claude -p ok`. Only `probe()` calls this and only
        `doctor` calls `probe()` (the run path uses the cheap available() login check), so normal
        adversarial runs pay no extra exec. Runs from a neutral temp cwd — the liveness check needs
        no repo context, so don't hand a real agent read access to whatever repo doctor ran in.
        Returns (ok, combined_output)."""
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
               "-c", "model_reasoning_effort=medium", "-o", path, "Reply with exactly: OK"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                               cwd=tempfile.gettempdir())
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                text = ""
            ok = r.returncode == 0 and bool((text or r.stdout).strip())
            return ok, (text + r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except OSError:
            return False, "oserror"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def probe(self) -> ProbeState:
        if not shutil.which("codex"):
            return ProbeState.NOT_INSTALLED
        if not self.available():                    # cheap login gate before the real exec
            return ProbeState.NOT_LOGGED_IN
        # Logged in — but only a real exec catches a too-old CLI the server rejects (400). This is
        # the doctor-only deep probe that fixes codex's "false green" asymmetry with claude.
        ok, out = self._probe_exec()
        if ok:
            return ProbeState.READY
        if self._too_old_marker in out.lower():
            return ProbeState.UNSUPPORTED_VERSION
        return ProbeState.BILLING_UNKNOWN           # logged in but exec returned nothing usable

    def version(self) -> str | None:
        """Best-effort CLI version string for provenance/replay; None if unavailable."""
        if not shutil.which("codex"):
            return None
        try:
            r = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return r.stdout.strip() or None

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 300) -> CaptureResult:
        # -o writes the machine-readable final message to a file for correct integrity capture,
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
            # answer there instead. The fallback still goes through the integrity checks and
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


@dataclass
class _KimiResolution:
    """Outcome of resolving which model `kimi -p` will actually serve.

    The three cases are deliberately distinct: a transient failure must never be mistaken for
    "this user has no Kimi", or one flaky subprocess would delete a family for the whole run.
    """
    alias: str | None = None        # verified Kimi alias to pin with -m
    transient_error: bool = False   # call failed/unparseable — unknown, retry later, do not cache
    provider_count: int = 0         # providers configured at all (0 => logged out, not repointed)


class KimiAdapter:
    """transport=cli, using local `kimi -p` (Kimi membership subscription) as the Kimi-family peer.

    Why this adapter is not a copy of ClaudeAdapter: kimi-code is a MULTI-PROVIDER client
    (`provider add`, `provider catalog` importing from models.dev, `-m <alias>`, and
    `default_model` in config.toml). A user can legitimately point `kimi -p` at a non-Moonshot
    model, at which point family_source="builtin" would assert a cross-family guarantee that is
    false — a claude-vs-"kimi" panel could really be claude-vs-claude. That redirect lives in a
    config FILE, so claude_cli_env()'s env stripping (which is what makes claude/codex safe as
    single-vendor CLIs) cannot reach it.

    So the family claim is re-derived from observed config on every run rather than hardcoded:
    _resolve() accepts only an alias served by the login-managed Kimi provider, and invoke() pins
    that exact alias with -m — the alias we verify IS the alias we run, so there is no
    probe-time/run-time gap and `default_model` is never trusted unverified. When nothing
    qualifies the voter is WITHHELD, not relabelled: a "kimi" voter that is not Kimi has negative
    value, since it consumes a panel slot while corrupting the family count. Withholding is loud
    (the family disappears from doctor and source_diversity); degrading would be quiet.

    Known, accepted residue: a hand-forged `managed:`-prefixed, kimi-typed, oauth-bearing provider
    whose baseUrl secretly proxies another vendor still qualifies. That hole is not closable
    locally — the user owns the machine, so any check we add is equally forgeable — and the threat
    model here is self-deception, not attack: the only victim is the user's own review. What this
    DOES catch is the unaware user (repointed by `provider catalog`, a tutorial, or a teammate)
    being told "cross-family verified" when it was not.
    """

    backend = "kimi-cli"
    model_family = "kimi"
    family_source = "builtin"
    product = "Kimi Code CLI (Kimi membership subscription)"
    install_hint = "install Kimi Code: https://moonshotai.github.io/kimi-code/"
    login_hint = "run `kimi`, then `/login` (needs a Kimi membership subscription)"
    unverified_hint = ("logged in, but no login-managed Kimi provider is configured — `kimi` is "
                       "pointed at another provider, so the kimi family cannot be verified and is "
                       "withheld; run `kimi provider list` to check, or use a BYO backend instead")
    # The login-managed provider's signature. `managed:` is created by `kimi login` (not by
    # `provider add`), `type` is kimi-code's OWN typing of the vendor (a models.dev-imported
    # OpenAI provider does not get "kimi"), and oauth means subscription auth over a pasted key.
    _MANAGED_PREFIX = "managed:"
    _PROVIDER_TYPE = "kimi"
    # `provider list --json` carries providers/models but no default; the human output is the only
    # surface exposing it. Anchored to a whole line so it cannot match inside another field.
    _DEFAULT_MODEL_RE = re.compile(r"^Default model:\s*(\S+)\s*$", re.MULTILINE)

    def __init__(self) -> None:
        self._resolved: str | None = None   # memoised on success only, never on failure

    def _cli_env(self) -> dict[str, str]:
        # Builtin adapter: reuse the mandatory CP_BYO_* stripping so a BYO backend's endpoint/token
        # can never leak into a subscription-authenticated kimi subprocess.
        return claude_cli_env()

    def _provider_config(self) -> dict | None:
        """Parse `kimi provider list --json` -> config dict; None on any transient failure.

        Token hygiene (0.1.5 BYO rule extends here): this output embeds `apiKey` and `baseUrl`.
        Both are empty/harmless for the oauth-managed provider, but a user-added provider's apiKey
        is a LIVE SECRET. Only the resolved alias escapes this method — the raw JSON must never
        reach logs, diagnostics, manifests, or provenance.
        """
        try:
            r = subprocess.run(["kimi", "provider", "list", "--json"], capture_output=True,
                               text=True, timeout=30, env=self._cli_env())
        except (subprocess.TimeoutExpired, OSError):
            return None
        if r.returncode != 0:
            return None
        try:
            cfg = json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
        return cfg if isinstance(cfg, dict) else None

    def _qualifying_aliases(self, cfg: dict) -> list[str]:
        """Model aliases served by the login-managed Kimi provider, sorted for determinism.

        All three signals are required together; any one alone is too weak to carry a builtin
        family claim. Sorted so two runs on one machine can never silently disagree on the pick.
        """
        providers, models = cfg.get("providers"), cfg.get("models")
        if not isinstance(providers, dict) or not isinstance(models, dict):
            return []
        managed = {pid for pid, p in providers.items()
                   if isinstance(p, dict)
                   and pid.startswith(self._MANAGED_PREFIX)
                   and p.get("type") == self._PROVIDER_TYPE
                   and p.get("oauth")}
        return sorted(alias for alias, m in models.items()
                      if isinstance(m, dict) and m.get("provider") in managed)

    def _configured_default(self) -> str | None:
        """The user's `Default model:` alias; None if unavailable (best-effort, never fatal)."""
        try:
            r = subprocess.run(["kimi", "provider", "list"], capture_output=True, text=True,
                               timeout=30, env=self._cli_env())
        except (subprocess.TimeoutExpired, OSError):
            return None
        m = self._DEFAULT_MODEL_RE.search(r.stdout)
        return m.group(1) if m else None

    def _resolve(self) -> _KimiResolution:
        """Decide which alias to pin. Success is memoised; failure never is."""
        if self._resolved:
            return _KimiResolution(alias=self._resolved)
        cfg = self._provider_config()
        if cfg is None:
            return _KimiResolution(transient_error=True)
        # Fail closed on a malformed shape: a truthy non-dict `providers` (e.g. a number from a
        # future/garbled --json) must withhold, never crash available()/probe() with a TypeError.
        providers = cfg.get("providers")
        n = len(providers) if isinstance(providers, dict) else 0
        aliases = self._qualifying_aliases(cfg)
        if not aliases:
            return _KimiResolution(provider_count=n)
        default = self._configured_default()
        if default in aliases:
            chosen = default              # honour the user's pick: all qualifying aliases are Kimi
        else:
            chosen = aliases[0]
            if default:
                # Never substitute silently — the user chose a default and we are not using it.
                print(f"warning: kimi default model {default!r} is not served by the login-managed "
                      f"Kimi provider; pinning {chosen!r} instead", file=sys.stderr)
        self._resolved = chosen
        return _KimiResolution(alias=chosen, provider_count=n)

    def available(self) -> bool:
        # Run-path discovery. Costs up to two `provider list` calls (--json for the providers, then
        # human output for the default) on the first call per run, memoised on success — the price
        # of not asserting an unverified family; codex's available() already shells out too.
        if not shutil.which("kimi"):
            return False
        return self._resolve().alias is not None

    def probe(self) -> ProbeState:
        if not shutil.which("kimi"):
            return ProbeState.NOT_INSTALLED
        res = self._resolve()
        if res.transient_error:
            return ProbeState.BILLING_UNKNOWN
        if res.alias is None:
            # No providers at all = never logged in; providers present but none Kimi = repointed.
            return (ProbeState.NOT_LOGGED_IN if res.provider_count == 0
                    else ProbeState.FAMILY_UNVERIFIED)
        # Config resolution only proves intent; a real call proves the subscription still
        # authenticates (an expired oauth token still leaves the provider entry in place). Runs
        # from a neutral temp cwd: `kimi -p` is an agent, and a liveness check needs no repo
        # context — don't hand it read access to whatever repo doctor ran in.
        try:
            r = subprocess.run(["kimi", "-p", "ok", "--output-format", "text", "-m", res.alias],
                               capture_output=True, text=True, timeout=90,
                               env=self._cli_env(), cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired:
            return ProbeState.BILLING_UNKNOWN
        except OSError:
            return ProbeState.NOT_INSTALLED
        # The `/login` marker is the ONLY authentication signal — kimi prints it when the
        # subscription is logged out or the oauth token expired. A bare nonzero exit without it is
        # a transient (network/rate-limit/billing/internal error): report it as unknown, not as
        # logout, so doctor never tells a logged-in user to re-login over a blip.
        if "/login" in (r.stdout + r.stderr).lower():
            return ProbeState.NOT_LOGGED_IN
        if r.returncode != 0:
            return ProbeState.BILLING_UNKNOWN
        return ProbeState.READY if r.stdout.strip() else ProbeState.BILLING_UNKNOWN

    def version(self) -> str | None:
        """Best-effort CLI version string for provenance/replay; None if unavailable."""
        if not shutil.which("kimi"):
            return None
        try:
            r = subprocess.run(["kimi", "--version"], capture_output=True, text=True,
                               timeout=20, env=self._cli_env())
        except (subprocess.TimeoutExpired, OSError):
            return None
        return r.stdout.strip() or None

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 150) -> CaptureResult:
        """Reasoning goes to stderr and the answer to stdout, so capture stdout alone.

        stdout is RENDERED, not raw: a "• " prefix on the first line, 2-space indented
        continuations, and JSON often inside a ```json fence. That still parses today because
        _extract_json scans for `{` and raw_decodes (skipping the bullet and fence) and
        check_capture/strip_marker compare with .strip() (absorbing the indent) — but nothing
        contracts kimi's renderer to stay parseable, so test_kimi_render_shape_still_parses pins
        it. If it ever breaks, capture fails loudly as capture_failed rather than yielding a
        wrong verdict.
        """
        res = self._resolve()
        if res.alias is None:
            # available() already gates this; belt-and-braces so an unverified family can never
            # reach a panel even if a caller skips discovery.
            return CaptureResult(False, "", CaptureFailureReason.EXIT_NONZERO)
        cmd = ["kimi", "-p", prompt, "--output-format", "text", "-m", res.alias]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=wall_timeout,
                               env=self._cli_env(), cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired:
            return CaptureResult(False, "", CaptureFailureReason.TIMEOUT)
        except OSError:
            return CaptureResult(False, "", CaptureFailureReason.EXIT_NONZERO)
        return check_capture(r.stdout, r.returncode)


class MockAdapter:
    """Structural-test adapter: return scripted output by voter_id without real model calls."""

    backend = "mock"
    model_family = "mock"
    family_source = "builtin"

    def __init__(self, scripted: dict[str, str], model_family: str = "mock",
                 family_source: str = "builtin"):
        self._scripted = scripted
        self.model_family = model_family
        self.family_source = family_source

    def available(self) -> bool:
        return True

    def probe(self) -> ProbeState:
        return ProbeState.READY

    def version(self) -> str | None:
        return "mock"

    def invoke(self, prompt: str, spec: VoterSpec, wall_timeout: int = 150) -> CaptureResult:
        return check_capture(self._scripted.get(spec.voter_id, ""), 0)
