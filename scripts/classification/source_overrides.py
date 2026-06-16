#!/usr/bin/env python3
"""Source-specific classification strategy helpers."""

from __future__ import annotations

from typing import Any


def source_strategy(source_id: str, source_overrides: dict[str, Any]) -> dict[str, Any]:
    strategy = source_overrides.get("sources", {}).get(source_id, {})
    return strategy if isinstance(strategy, dict) else {}

