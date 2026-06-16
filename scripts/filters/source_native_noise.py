#!/usr/bin/env python3
"""Source-native noise filtering."""

from __future__ import annotations

import re
from typing import Any

try:
    from classification.rule_matcher import any_keyword_matches
except ImportError:  # pragma: no cover - package import fallback
    from ..classification.rule_matcher import any_keyword_matches


def should_drop_by_source_native_noise(item: dict[str, Any], noise_map: dict[str, Any]) -> bool:
    source_id = str(item.get("source_id", "")).strip()
    source_rules = noise_map.get("sources", {}).get(source_id, {})
    if not isinstance(source_rules, dict):
        return False

    title = str(item.get("title", ""))
    summary = str(item.get("summary", ""))
    section = str(item.get("section", ""))
    rank_section = str(item.get("rank_section", ""))
    url = str(item.get("canonical_url") or item.get("source_url") or "")
    text = f"{title} {summary} {section} {rank_section}".lower()

    keep_overrides = source_rules.get("keep_overrides", [])
    if isinstance(keep_overrides, list) and any_keyword_matches(text, [str(value) for value in keep_overrides]):
        return False

    normalized_section = native_label(section)
    normalized_rank_section = native_label(rank_section)
    drop_sections = {native_label(value) for value in source_rules.get("drop_sections", [])}
    drop_rank_sections = {native_label(value) for value in source_rules.get("drop_rank_sections", [])}

    if normalized_section and normalized_section in drop_sections:
        return True
    if normalized_rank_section and normalized_rank_section in drop_rank_sections:
        return True

    for pattern in source_rules.get("drop_url_patterns", []):
        if str(pattern) and str(pattern) in url:
            return True
    return False


def native_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())

