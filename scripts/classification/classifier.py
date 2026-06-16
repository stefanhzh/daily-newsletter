#!/usr/bin/env python3
"""Classification entry point used by pipeline.py."""

from __future__ import annotations

from typing import Any

from .models import ClassificationResult
from .rule_matcher import infer_primary_bucket, infer_secondary_tags
from .source_native import direct_category_from_native
from .source_overrides import source_strategy


def build_classification_text(raw_item: dict[str, Any]) -> str:
    section = str(raw_item.get("section", "")).strip()
    source_tags = " ".join(str(tag) for tag in raw_item.get("source_tags", []) if tag)
    title = str(raw_item.get("title", "")).strip()
    summary = str(raw_item.get("summary", "")).strip()
    return f"{title} {summary} {section} {source_tags}"


def classify_raw_item(
    raw_item: dict[str, Any],
    *,
    category_map: dict[str, str],
    category_rules: dict[str, Any],
    source_overrides: dict[str, Any],
    source_native_taxonomy: dict[str, Any],
) -> ClassificationResult:
    source_id = str(raw_item.get("source_id", "")).strip()
    text = build_classification_text(raw_item)
    strategy = source_strategy(source_id, source_overrides)

    native_category = ""
    if strategy.get("hard_category_override") is True:
        native_category = direct_category_from_native(raw_item, source_native_taxonomy)

    if native_category:
        bucket = _bucket_for_category(native_category, category_map)
        primary_category = native_category
        scores: dict[str, int] = {}
        reasons = ["source_native_hard_override"]
    else:
        bucket, scores, reasons = infer_primary_bucket(
            text,
            source_id,
            category_rules,
            source_overrides,
            native_section=str(raw_item.get("section", "")),
        )
        primary_category = category_map.get(bucket, next(iter(category_map.values())))

    return ClassificationResult(
        primary_category=primary_category,
        category_bucket=bucket,
        secondary_tags=infer_secondary_tags(primary_category, text, category_rules),
        classification_source="rule_matcher",
        classification_reason="; ".join(reasons),
        classification_text=text,
        scores=scores,
    )


def _bucket_for_category(category: str, category_map: dict[str, str]) -> str:
    for bucket, label in category_map.items():
        if label == category:
            return bucket
    return "macro"
