#!/usr/bin/env python3
"""Rule-based seven-board classification."""

from __future__ import annotations

import re
from typing import Any


def normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    normalized_keyword = keyword.lower()
    if re.fullmatch(r"[a-z0-9]+", normalized_keyword) and len(normalized_keyword) <= 3:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", lowered_text))
    return normalized_keyword in lowered_text


def any_keyword_matches(lowered_text: str, keywords: list[str]) -> bool:
    return any(keyword_matches(lowered_text, keyword) for keyword in keywords)


def keyword_bucket_scores(text: str, category_rules: dict[str, Any]) -> dict[str, int]:
    lowered = text.lower()
    keyword_rules = category_rules.get("category_keyword_rules", {})
    scores: dict[str, int] = {bucket: 0 for bucket in keyword_rules}
    for bucket, keywords in keyword_rules.items():
        for keyword in keywords:
            if keyword_matches(lowered, str(keyword)):
                scores[bucket] += 1
    return scores


def infer_primary_bucket(
    text: str,
    source_id: str,
    category_rules: dict[str, Any],
    source_overrides: dict[str, Any],
    native_section: str = "",
) -> tuple[str, dict[str, int], list[str]]:
    scores = keyword_bucket_scores(text, category_rules)
    lowered = text.lower()
    reasons: list[str] = []

    _apply_native_section_boost(native_section, source_id, source_overrides, scores, reasons)
    _apply_native_section_context_boost(native_section, lowered, source_id, source_overrides, scores, reasons)
    _apply_source_boosts(lowered, source_id, source_overrides, scores, reasons)
    _apply_strong_rules(lowered, category_rules, scores, reasons)

    tech_route = _tech_company_route(lowered, category_rules)
    if tech_route:
        reasons.append(f"tech_company_route:{tech_route}")
        return tech_route, scores, reasons

    priority_bucket = _priority_bucket(lowered, scores, category_rules)
    if priority_bucket:
        reasons.append(f"priority_rule:{priority_bucket}")
        return priority_bucket, scores, reasons

    winner = max(scores.items(), key=lambda pair: pair[1])[0]
    if scores[winner] == 0:
        winner = category_rules.get("fallbacks", {}).get("source_bucket", {}).get(
            source_id,
            category_rules.get("fallbacks", {}).get("default_bucket", "macro"),
        )
        reasons.append(f"fallback:{winner}")
    else:
        reasons.append(f"keyword_score:{winner}={scores[winner]}")
    return winner, scores, reasons


def infer_secondary_tags(category: str, text: str, category_rules: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    lowered = text.lower()
    for rule in category_rules.get("secondary_tag_rules", []):
        if any_keyword_matches(lowered, [str(keyword) for keyword in rule.get("keywords", [])]):
            tag = str(rule.get("tag", "")).strip()
            if tag:
                tags.append(tag)
    if not tags:
        tags.append(normalize_text(category) or "general")
    return tags[:2]


def _apply_source_boosts(
    lowered: str,
    source_id: str,
    source_overrides: dict[str, Any],
    scores: dict[str, int],
    reasons: list[str],
) -> None:
    for rule in source_overrides.get("source_boosts", []):
        source_ids = {str(value) for value in rule.get("source_ids", [])}
        if source_id not in source_ids:
            continue
        keywords = [str(keyword) for keyword in rule.get("keywords", [])]
        if not any_keyword_matches(lowered, keywords):
            continue
        for bucket, delta in rule.get("score_delta", {}).items():
            scores[str(bucket)] = scores.get(str(bucket), 0) + int(delta)
        reasons.append(f"source_boost:{source_id}")


def _apply_native_section_boost(
    native_section: str,
    source_id: str,
    source_overrides: dict[str, Any],
    scores: dict[str, int],
    reasons: list[str],
) -> None:
    section = str(native_section or "").strip().lower()
    if not section:
        return
    source_rules = source_overrides.get("sources", {}).get(source_id, {})
    if not isinstance(source_rules, dict):
        return
    boosts = source_rules.get("native_section_soft_boosts", {})
    if not isinstance(boosts, dict):
        return
    boost = boosts.get(section)
    if not isinstance(boost, dict):
        return
    for bucket, delta in boost.items():
        scores[str(bucket)] = scores.get(str(bucket), 0) + int(delta)
    reasons.append(f"native_section_soft_boost:{source_id}:{section}")


def _apply_native_section_context_boost(
    native_section: str,
    lowered: str,
    source_id: str,
    source_overrides: dict[str, Any],
    scores: dict[str, int],
    reasons: list[str],
) -> None:
    section = str(native_section or "").strip().lower()
    if not section:
        return
    source_rules = source_overrides.get("sources", {}).get(source_id, {})
    if not isinstance(source_rules, dict):
        return
    section_rules = source_rules.get("native_section_context_boosts", {}).get(section, [])
    if not isinstance(section_rules, list):
        return
    for rule in section_rules:
        if not isinstance(rule, dict):
            continue
        keywords = [str(keyword) for keyword in rule.get("keywords", [])]
        if not any_keyword_matches(lowered, keywords):
            continue
        bucket = str(rule.get("bucket", ""))
        if not bucket:
            continue
        scores[bucket] = scores.get(bucket, 0) + int(rule.get("delta", 0))
        reasons.append(f"native_section_context_boost:{source_id}:{section}:{bucket}")


def _apply_strong_rules(
    lowered: str,
    category_rules: dict[str, Any],
    scores: dict[str, int],
    reasons: list[str],
) -> None:
    for rule in category_rules.get("strong_rules", []):
        keywords = [str(keyword) for keyword in rule.get("keywords", [])]
        if not any_keyword_matches(lowered, keywords):
            continue
        bucket = str(rule.get("bucket", ""))
        if not bucket:
            continue
        scores[bucket] = scores.get(bucket, 0) + int(rule.get("delta", 0))
        reasons.append(f"strong_rule:{bucket}")


def _tech_company_route(lowered: str, category_rules: dict[str, Any]) -> str:
    routing = category_rules.get("tech_company_routing", {})
    context_keywords = [str(keyword) for keyword in routing.get("context_keywords", [])]
    if not any_keyword_matches(lowered, context_keywords):
        return ""

    candidates: list[tuple[int, int, str]] = []
    for index, route in enumerate(routing.get("routes", [])):
        if not isinstance(route, dict):
            continue
        bucket = str(route.get("bucket", ""))
        if not bucket:
            continue
        keywords = [str(keyword) for keyword in route.get("keywords", [])]
        weak_keywords = [str(keyword) for keyword in route.get("weak_keywords", [])]
        hard_matches = sum(1 for keyword in keywords if keyword_matches(lowered, keyword))
        weak_matches = sum(1 for keyword in weak_keywords if keyword_matches(lowered, keyword))
        if hard_matches == 0:
            # Weak signals such as "China" can support a route, but should not
            # decide the category on their own.
            continue
        route_score = hard_matches * 2 + weak_matches
        priority = int(route.get("priority", index + 1))
        candidates.append((route_score, -priority, bucket))

    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][2]


def _priority_bucket(lowered: str, scores: dict[str, int], category_rules: dict[str, Any]) -> str:
    rules = category_rules.get("priority_rules", {})
    extensions = category_rules.get("priority_rule_extensions", {})

    def extended_keywords(name: str) -> list[str]:
        return [str(value) for value in rules.get(name, [])] + [str(value) for value in extensions.get(name, [])]

    policy_strong = any_keyword_matches(lowered, extended_keywords("policy_strong"))
    macro_strong = any_keyword_matches(lowered, extended_keywords("macro_strong"))
    market_strong = any_keyword_matches(lowered, extended_keywords("market_strong"))
    market_direct = any_keyword_matches(lowered, extended_keywords("market_direct"))
    industry_strong = any_keyword_matches(lowered, extended_keywords("industry_strong"))
    industry_direct = any_keyword_matches(lowered, extended_keywords("industry_direct"))

    if policy_strong and scores.get("policy", 0) >= max(scores.get("geopolitics", 0), scores.get("industry", 0), scores.get("capital_markets", 0)):
        return "policy"
    if macro_strong and scores.get("macro", 0) >= max(scores.get("geopolitics", 0), scores.get("capital_markets", 0)):
        return "macro"
    if market_strong and market_direct:
        return "capital_markets"
    if industry_strong and industry_direct:
        return "industry"
    if market_strong and scores.get("capital_markets", 0) >= scores.get("geopolitics", 0):
        return "capital_markets"
    if industry_strong and scores.get("industry", 0) >= scores.get("geopolitics", 0):
        return "industry"
    return ""
