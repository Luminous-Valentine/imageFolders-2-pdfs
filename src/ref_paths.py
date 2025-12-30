"""Utilities for reading tool_settings.txt (KEY=VALUE with ${KEY} expansion).

This repo historically used reference_paths.txt; most tools support both:
- tool_settings.txt (preferred)
- reference_paths.txt (legacy)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_CONFIG_FILENAME = "tool_settings.txt"
LEGACY_CONFIG_FILENAME = "reference_paths.txt"


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_ref_path(*, repo_root: Optional[Path] = None) -> Path:
    root = repo_root or get_repo_root()
    preferred = root / DEFAULT_CONFIG_FILENAME
    legacy = root / LEGACY_CONFIG_FILENAME
    if preferred.exists() and preferred.is_file():
        return preferred
    if legacy.exists() and legacy.is_file():
        return legacy
    return preferred


def read_reference_text_best_effort(path: Path) -> Dict[str, str]:
    try:
        if path.suffix.lower() != ".txt":
            return {}
        if not path.exists() or path.is_dir():
            return {}
        content = path.read_text(encoding="utf-8-sig")
    except Exception:
        return {}

    config: Dict[str, str] = {}
    for raw_line in re.split(r"\r?\n", content):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip().upper()] = value.strip()
    return config


def resolve_configured_path(ref_path: Path, value: str) -> Path:
    trimmed = value.strip().strip('"')
    configured = Path(trimmed)
    if configured.is_absolute():
        return configured
    return (ref_path.parent / configured).resolve()


def resolve_ref_value(
    config: Dict[str, str],
    key: str,
    *,
    default: Optional[str] = None,
    required: bool = False,
    _stack: Optional[List[str]] = None,
) -> str:
    stack = [] if _stack is None else _stack
    key_upper = key.strip().upper()

    raw = config.get(key_upper, "")
    raw = raw.strip()
    if not raw and default is not None:
        raw = default

    if not raw:
        if required:
            raise ValueError(f"Missing required key in reference text: {key_upper}")
        return ""

    if key_upper in stack:
        chain = " -> ".join([*stack, key_upper])
        raise ValueError(f"Detected cyclic reference in reference text: {chain}")

    stack.append(key_upper)

    def replace_var(match: re.Match[str]) -> str:
        var = match.group(1).strip().upper()
        return resolve_ref_value(config, var, default=None, required=True, _stack=stack)

    expanded = re.sub(r"\$\{([^}]+)\}", replace_var, raw)

    expanded_key = expanded.strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", expanded_key or ""):
        maybe_key = expanded_key.upper()
        if maybe_key in config and maybe_key != key_upper:
            expanded = resolve_ref_value(
                config,
                maybe_key,
                default=None,
                required=True,
                _stack=stack,
            )

    stack.pop()
    return expanded.strip()

