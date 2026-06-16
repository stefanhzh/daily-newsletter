from __future__ import annotations

import hashlib
from typing import Any

from pipeline_models import CandidateItem, EventCluster

from .models import RawItemMeta, RuleScore


def build_source_index(sources_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for source in sources_config.get("sources", []):
        source_id = source.get("id", "")
        if not source_id:
            continue
        index[source_id] = source
        for alias in source.get("aliases", []):
            index[alias] = source
    return index


def build_raw_meta_index(raw_items: list[dict[str, Any]]) -> dict[tuple[str, str], RawItemMeta]:
    index: dict[tuple[str, str], RawItemMeta] = {}
    for raw in raw_items:
        source_id = str(raw.get("source_id", "")).strip()
        title = str(raw.get("title", "")).strip()
        if not source_id or not title:
            continue
        rank_position = _coerce_rank(raw.get("rank_position"))
        source_tags = raw.get("source_tags") or []
        if not isinstance(source_tags, list):
            source_tags = [str(source_tags)]
        index[(source_id.lower(), title.lower())] = RawItemMeta(
            source_id=source_id,
            title=title,
            rank_section=str(raw.get("rank_section") or "").strip(),
            rank_position=rank_position,
            discovery_method=str(raw.get("discovery_method") or "").strip(),
            source_tags=[str(tag) for tag in source_tags],
        )
    return index


def raw_meta_for_item(
    item: CandidateItem,
    raw_meta_index: dict[tuple[str, str], RawItemMeta],
) -> RawItemMeta:
    return raw_meta_index.get((item.source_id.lower(), item.title.lower()), RawItemMeta(source_id=item.source_id, title=item.title))


def score_cluster_rules(
    cluster: EventCluster,
    *,
    source_index: dict[str, dict[str, Any]],
    raw_meta_index: dict[tuple[str, str], RawItemMeta],
) -> RuleScore:
    members = [cluster.primary_item, *cluster.related_items]
    platform_candidates = [_platform_score(item, source_index.get(item.source_id, {})) for item in members]
    rank_candidates = [_rank_score(raw_meta_for_item(item, raw_meta_index)) for item in members]

    platform_score, platform_reason = max(platform_candidates, key=lambda result: result[0])
    rank_score, rank_reason = max(rank_candidates, key=lambda result: result[0])
    total = round(platform_score + rank_score, 2)
    return RuleScore(
        platform_score=round(platform_score, 2),
        rank_score=round(rank_score, 2),
        total=total,
        platform_reason=platform_reason,
        rank_reason=rank_reason,
    )


def scoring_cache_key(cluster: EventCluster) -> str:
    text = "|".join([cluster.primary_item.title, *(item.title for item in cluster.related_items)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _platform_score(item: CandidateItem, source_meta: dict[str, Any]) -> tuple[float, str]:
    tier = str(source_meta.get("tier") or "T2")
    group = str(source_meta.get("group") or "media")
    role = str(source_meta.get("role") or "discovery_and_context")

    tier_points = {
        "T1": 14.0,
        "T1_5": 11.0,
        "T2": 7.0,
    }.get(tier, 6.0)
    group_points = {
        "regulator": 7.0,
        "exchange": 7.0,
        "official": 7.0,
        "wire": 6.0,
        "media": 4.5,
        "sector_media": 3.5,
        "technical_platform": 3.0,
        "social": 1.5,
        "kol": 1.0,
    }.get(group, 3.0)
    role_points = {
        "verification": 4.0,
        "discovery_and_verification": 3.5,
        "discovery_and_context": 2.5,
        "context": 2.0,
        "directed_monitoring": 1.5,
        "discovery": 1.5,
        "discovery_only": 0.5,
    }.get(role, 1.5)

    score = min(25.0, tier_points + group_points + role_points)
    reason = f"{item.source_id}: tier={tier}({tier_points}), group={group}({group_points}), role={role}({role_points})"
    return score, reason


def _rank_score(meta: RawItemMeta) -> tuple[float, str]:
    position = meta.rank_position
    section = meta.rank_section
    position_points = _rank_position_points(position)
    section_points = _rank_section_points(section)
    score = min(25.0, position_points + section_points)
    position_label = f"#{position}" if position else "unranked"
    reason = f"{meta.source_id}: rank_position={position_label}({position_points}), rank_section={section or 'none'}({section_points})"
    return score, reason


def _rank_position_points(position: int | None) -> float:
    if position is None or position <= 0:
        return 6.0
    if position == 1:
        return 15.0
    if position <= 3:
        return 13.0
    if position <= 5:
        return 11.0
    if position <= 10:
        return 8.0
    if position <= 20:
        return 5.0
    return 3.0


def _rank_section_points(section: str) -> float:
    normalized = section.strip().lower()
    if not normalized:
        return 2.0
    high_confidence = {
        "homepage_top",
        "news_homepage",
        "business_homepage",
        "technology_homepage",
        "top_headlines",
    }
    medium_confidence = {
        "homepage_rank_proxy",
        "important_flash",
        "headline",
        "hot_article",
        "latest",
    }
    popularity = {
        "most_popular",
        "hotrank",
        "hot_rank",
        "trending",
    }
    if normalized in high_confidence:
        return 10.0
    if normalized in medium_confidence:
        return 8.0
    if normalized in popularity:
        return 6.0
    if "homepage" in normalized or "top" in normalized:
        return 8.0
    if "hot" in normalized or "popular" in normalized or "trend" in normalized:
        return 6.0
    return 4.0


def _coerce_rank(value: Any) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None

