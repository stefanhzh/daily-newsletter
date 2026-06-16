#!/usr/bin/env python3
"""Shared helpers for optional authenticated source sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTH_STATE_DIR = ROOT / "config" / "auth_states"


def source_env_prefix(source_id: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", source_id.upper()).strip("_")


def storage_state_path(source_id: str) -> Path:
    specific = os.environ.get(f"{source_env_prefix(source_id)}_STORAGE_STATE")
    if specific:
        return Path(specific).expanduser()

    base_dir = Path(os.environ.get("DAILY_NEWSLETTER_AUTH_STATE_DIR", DEFAULT_AUTH_STATE_DIR)).expanduser()
    return base_dir / f"{source_id}.storage_state.json"


def existing_storage_state_path(source_id: str) -> Path | None:
    path = storage_state_path(source_id)
    return path if path.exists() else None


def playwright_storage_state(source_id: str) -> str | None:
    path = existing_storage_state_path(source_id)
    return str(path) if path else None


def cookie_header_from_storage_state(source_id: str, domain_hints: Iterable[str]) -> str:
    path = existing_storage_state_path(source_id)
    if not path:
        return ""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    normalized_hints = [hint.lower().lstrip(".") for hint in domain_hints if hint]
    pairs: list[str] = []
    seen: set[str] = set()
    for cookie in payload.get("cookies", []):
        name = cookie.get("name")
        value = cookie.get("value")
        domain = (cookie.get("domain") or "").lower().lstrip(".")
        if not name or value is None or not domain:
            continue
        if normalized_hints and not any(domain.endswith(hint) or hint.endswith(domain) for hint in normalized_hints):
            continue
        if name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)
