"""Persistent user config — the tool's first stored state.

challenge-plans is otherwise stateless (backends discovered live, BYO via env). This module holds
ONE thing: the user's default adversary panel (which model families run when neither `--families`
nor a fuller selection is given). It stores family *names* only — never credentials, endpoints, or
tokens — so it cannot become a place secrets leak into.

Format is YAML (the project already depends on PyYAML and `weigh` reads YAML), not TOML: the target
is Python >=3.10, which has no stdlib `tomllib`, and adding a TOML dependency to store a single list
would be gratuitous.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def config_path() -> Path:
    """Resolved config file path. Honours CHALLENGE_PLANS_CONFIG (tests/overrides), then XDG."""
    override = os.environ.get("CHALLENGE_PLANS_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "challenge-plans" / "config.yaml"


def load_config() -> dict:
    """Parse the config file -> dict; {} if absent. A malformed file warns and is treated as empty
    (a broken config must degrade to defaults, never crash a run)."""
    import yaml
    path = config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except UnicodeDecodeError:
        print(f"warning: config {path} is not UTF-8; ignoring it and using the default panel",
              file=sys.stderr)
        return {}
    except OSError as e:
        print(f"warning: cannot read config {path}: {e}", file=sys.stderr)
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"warning: config {path} is not valid YAML ({e}); ignoring it", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def read_default_families() -> list[str] | None:
    """The configured default panel as a list of family names, or None if unset.

    The reader preserves None (key absent) vs [] (explicitly emptied) faithfully so `config show`
    can report them differently. Selection treats both as "use the built-in default" — an empty
    panel is not a runnable state, and collapsing it here would only split doctor from run.
    """
    panel = load_config().get("panel")
    if panel is None:
        return None
    if not isinstance(panel, dict):
        print(f"warning: config `panel` must be a mapping (got {type(panel).__name__}); "
              f"ignoring it and using the default panel", file=sys.stderr)
        return None
    fams = panel.get("families")
    if fams is None:
        return None
    if not isinstance(fams, list):
        # A common mistype: `families: claude,codex` (a string) instead of a list. Never silently
        # discard a config the user believes is active — say so, then fall back to the default.
        print(f"warning: config `panel.families` must be a list like [claude, codex] "
              f"(got {type(fams).__name__}); ignoring it and using the default panel",
              file=sys.stderr)
        return None
    # Normalise: lower-cased, stripped, de-duplicated in order, non-strings dropped.
    seen, out = set(), []
    for f in fams:
        if not isinstance(f, str):
            continue
        name = f.strip().lower()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def write_default_families(families: list[str]) -> Path:
    """Persist the default panel. Creates the config dir. Returns the path written."""
    import yaml
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Read-merge to preserve any other top-level keys. Today `panel` is the only key, so a read that
    # failed to {} loses nothing; revisit this (distinguish absent from read-error) if config grows.
    data = load_config()
    data.setdefault("panel", {})
    if not isinstance(data["panel"], dict):
        data["panel"] = {}
    data["panel"]["families"] = families
    body = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    # Atomic write: a crash mid-write must never truncate an existing config into corruption. Write
    # a sibling temp file (same dir → same filesystem, so os.replace is atomic) and swap it in.
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
