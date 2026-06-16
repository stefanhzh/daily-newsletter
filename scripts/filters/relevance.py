#!/usr/bin/env python3
"""Generic relevance and title-noise filters."""

from __future__ import annotations

from typing import Any

try:
    from classification.rule_matcher import keyword_bucket_scores
except ImportError:  # pragma: no cover - package import fallback
    from ..classification.rule_matcher import keyword_bucket_scores


NOISE_TITLE_PATTERNS = [
    "版权声明",
    "举报",
    "公告",
    "受理和处置规则",
]

GLOBAL_SKIP_KEYWORDS = [
    "eurovision",
    "song contest",
    "dodgers",
    "baseball",
    "cannes contender",
    "mount everest",
    "software engineer doesn",
    "mortgage payment",
    "top wall street analysts",
    "3 big things we're watching",
    "hottest stock themes",
]

SOURCE_SKIP_RULES = {
    "ap": [
        "(ap photo/",
    ],
    "cailian": [
        "【早报】",
        "周末要闻",
        "下周看点",
        "一周前瞻",
        "日报",
        "盘点",
        "对话科创家",
        "策略来了",
    ],
    "cnbc": [
        "top wall street analysts",
        "3 big things we're watching",
        "mortgage payment",
        "hottest stock themes",
    ],
    "yicai": [
        "版权声明",
        "举报",
        "公告",
        "回应拿下第五冠",
        "cmg中国电影盛典",
        "澳车北上",
        "积分落户",
        "调拨中央防汛抗旱物资",
        "壹快评",
        "点金丨",
        "实话世经",
    ],
}

SOURCE_MIN_RELEVANCE = {
    ("yicai", "latest"): 2,
    ("yicai", "featured"): 1,
    ("cnbc", "top-news"): 1,
    ("cailian", "depth_list"): 1,
}


def should_skip_ingested_item(item: dict[str, Any]) -> bool:
    title = str(item.get("title", "")).strip()
    if not title:
        return True
    lowered = title.lower()
    if any(pattern in title for pattern in NOISE_TITLE_PATTERNS):
        return True
    if any(keyword in lowered for keyword in GLOBAL_SKIP_KEYWORDS):
        return True
    source_id = str(item.get("source_id", "")).strip()
    for keyword in SOURCE_SKIP_RULES.get(source_id, []):
        if keyword.lower() in lowered:
            return True
    return False


def source_relevance_gate(source_id: str, section: str, text: str, category_rules: dict[str, Any]) -> bool:
    scores = keyword_bucket_scores(text, category_rules)
    min_required = SOURCE_MIN_RELEVANCE.get((source_id, section))
    if min_required is None:
        return True
    strongest = max(scores.values()) if scores else 0
    return strongest >= min_required
