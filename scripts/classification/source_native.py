#!/usr/bin/env python3
"""Source-native taxonomy helpers."""

from __future__ import annotations

import re
from typing import Any


def disabled_sources(source_native_taxonomy: dict[str, Any]) -> set[str]:
    disabled: set[str] = set()
    for source_id, rules in source_native_taxonomy.get("sources", {}).items():
        if isinstance(rules, dict) and rules.get("daily_section_news_enabled") is False:
            disabled.add(source_id)
    return disabled


def direct_category_from_native(item: dict[str, Any], source_native_taxonomy: dict[str, Any]) -> str:
    """Return an explicit native-section mapping when one is configured.

    Current classifier behavior does not hard-apply this by default; this helper
    exists so source-native mapping can be enabled source-by-source later.
    """
    source_id = str(item.get("source_id", "")).strip()
    section = _native_label(item.get("section", ""))
    if not section:
        return ""

    source_rules = source_native_taxonomy.get("sources", {}).get(source_id, {})
    if isinstance(source_rules, dict):
        mapped = source_rules.get("section_map", {}).get(section)
        if mapped:
            return str(mapped)

    mapped = source_native_taxonomy.get("global_section_map", {}).get(section)
    return str(mapped) if mapped else ""


def _native_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())

