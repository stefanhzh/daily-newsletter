#!/usr/bin/env python3
"""
Minimal deterministic pipeline for daily-newsletter.

This module keeps the first runnable version dependency-light:
- standard library only
- JSON config support out of the box
- simple clustering and scoring to prove the architecture
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from json import loads
from pathlib import Path
from typing import Any

from classification.classifier import build_classification_text, classify_raw_item
from classification.source_native import disabled_sources as source_native_disabled_sources
from clustering.clusterer import cluster_items
from clustering.rules import clustering_rules, extract_named_tokens, slugify_event_key
from filters.relevance import should_skip_ingested_item, source_relevance_gate
from filters.source_native_noise import should_drop_by_source_native_noise
from pipeline_models import CandidateItem, EventCluster, PipelineResult


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))


def load_configs() -> dict[str, Any]:
    config_dir = ROOT / "config"
    return {
        "sources": load_json(config_dir / "sources.json"),
        "scoring": load_json(config_dir / "scoring.json"),
        "thresholds": load_json(config_dir / "thresholds.json"),
        "watchlists": load_json(config_dir / "watchlists.json"),
        "category_rules": load_json(config_dir / "category_rules.json"),
        "clustering_rules": load_optional_json(config_dir / "clustering_rules.json"),
        "source_category_overrides": load_optional_json(config_dir / "source_category_overrides.json"),
        "source_native_taxonomy": load_optional_json(config_dir / "source_native_taxonomy_map.json"),
        "source_native_noise": load_optional_json(config_dir / "source_native_noise_map.json"),
    }


def load_optional_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return load_json(path)


def load_sample_items() -> list[CandidateItem]:
    raw = load_json(ROOT / "data" / "sample_items.json")
    return [CandidateItem(**item) for item in raw]


def load_items_from_path(path: Path, configs: dict[str, Any] | None = None) -> list[CandidateItem]:
    raw = load_json(path)
    if raw and isinstance(raw, list) and "published_at" in raw[0] and "dimensions" not in raw[0]:
        if configs is None:
            configs = load_configs()
        return normalize_ingested_items(raw, configs)
    return [CandidateItem(**item) for item in raw]


def build_source_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for source in config["sources"]:
        index[source["id"]] = source
        for alias in source.get("aliases", []):
            index[alias] = source
    return index


def daily_section_disabled_sources() -> set[str]:
    taxonomy_path = ROOT / "config" / "source_native_taxonomy_map.json"
    if not taxonomy_path.exists():
        return set()
    try:
        taxonomy = load_json(taxonomy_path)
    except Exception:
        return set()
    return source_native_disabled_sources(taxonomy)


def _category_keys(configs: dict[str, Any]) -> list[str]:
    return list(configs["thresholds"]["selection_thresholds"].keys())


def _category_map(configs: dict[str, Any]) -> dict[str, str]:
    keys = _category_keys(configs)
    names = [
        "geopolitics",
        "macro",
        "policy",
        "industry",
        "technology",
        "capital_markets",
        "risk",
    ]
    return {name: keys[idx] for idx, name in enumerate(names) if idx < len(keys)}


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hours_ago_from_iso(value: str) -> int:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return 999
    delta = datetime.now(timezone.utc) - parsed
    return max(0, int(delta.total_seconds() // 3600))


def _infer_dimensions(
    *,
    source_meta: dict[str, Any],
    category_bucket: str,
    hours_ago: int,
    text: str,
) -> dict[str, float]:
    tier = source_meta.get("tier", "T2")
    group = source_meta.get("group", "media")

    credibility_map = {"T1": 4.9, "T1_5": 4.6, "T2": 4.0}
    importance_map = {"wire": 4.2, "official": 4.4, "regulator": 4.5, "exchange": 4.5, "media": 3.8, "sector_media": 3.5}
    investor_map = {
        "geopolitics": 4.4,
        "macro": 4.6,
        "policy": 4.6,
        "industry": 4.1,
        "technology": 3.8,
        "capital_markets": 4.7,
        "risk": 4.7,
    }
    breadth_map = {
        "geopolitics": 4.6,
        "macro": 4.5,
        "policy": 4.3,
        "industry": 3.8,
        "technology": 3.7,
        "capital_markets": 4.2,
        "risk": 4.4,
    }

    novelty = 4.8 if hours_ago <= 6 else 4.3 if hours_ago <= 24 else 3.8
    importance = importance_map.get(group, 3.8)
    investor_relevance = investor_map.get(category_bucket, 4.0)
    breadth = breadth_map.get(category_bucket, 4.0)
    credibility = credibility_map.get(tier, 4.0)

    lowered = text.lower()
    if any(token in lowered for token in ["ipo", "listing", "fed", "central bank", "中美", "制裁", "立案", "war", "outbreak"]):
        importance += 0.4
        investor_relevance += 0.4
    if any(token in lowered for token in ["commentary", "壹快评", "opinion", "analysis"]):
        breadth -= 0.2
    if any(token in lowered for token in ["killed", "dead", "地震", "outbreak", "违约"]):
        breadth += 0.2

    return {
        "importance": min(5.0, round(importance, 2)),
        "novelty": min(5.0, round(novelty, 2)),
        "investor_relevance": min(5.0, round(investor_relevance, 2)),
        "credibility": min(5.0, round(credibility, 2)),
        "breadth": min(5.0, round(breadth, 2)),
    }


def _infer_attributes(category_bucket: str, text: str, cluster_rules: dict[str, Any]) -> dict[str, Any]:
    lowered = text.lower()
    entity_count = len(
        extract_named_tokens(
            CandidateItem(
                id="",
                title=text,
                summary="",
                source_id="",
                published_hours_ago=0,
                primary_category="",
                secondary_tags=[],
                event_key="",
                dimensions={},
                attributes={},
                source_url="",
            ),
            cluster_rules,
        )
    )
    return {
        "policy_shock": category_bucket in {"geopolitics", "policy"} and any(token in lowered for token in ["sanction", "tariff", "制裁", "关税", "regulation", "证监会", "国安部"]),
        "cross_asset": category_bucket in {"geopolitics", "macro", "capital_markets"} and any(token in lowered for token in ["oil", "yield", "market", "stock", "债", "汇率", "通胀"]),
        "sector_structure": category_bucket == "industry",
        "deal_activity": category_bucket == "capital_markets" and any(token in lowered for token in ["ipo", "merger", "acquisition", "并购", "上市", "融资"]),
        "exit_environment": any(token in lowered for token in ["ipo", "valuation", "listing", "融资", "估值"]),
        "commentary_only": any(token in lowered for token in ["commentary", "壹快评", "opinion"]),
        "narrow_single_company": category_bucket in {"technology", "industry"} and not any(token in lowered for token in ["analysts suggest these 3 stocks", "copyright"]) and entity_count <= 1,
    }


def normalize_ingested_items(raw_items: list[dict[str, Any]], configs: dict[str, Any]) -> list[CandidateItem]:
    source_index = build_source_index(configs["sources"])
    category_keys = _category_keys(configs)
    cluster_rules = clustering_rules(configs)
    disabled_sources = source_native_disabled_sources(configs.get("source_native_taxonomy", {}))
    noise_map = configs.get("source_native_noise", {})
    items: list[CandidateItem] = []

    for raw in raw_items:
        if should_skip_ingested_item(raw):
            continue

        source_id = str(raw.get("source_id", "")).strip()
        if source_id in disabled_sources:
            continue
        if should_drop_by_source_native_noise(raw, noise_map):
            continue
        section = str(raw.get("section", "")).strip()
        title = str(raw.get("title", "")).strip()
        summary = str(raw.get("summary", "")).strip()
        text = build_classification_text(raw)
        if not source_relevance_gate(source_id, section, text, configs["category_rules"]):
            continue
        classification = classify_raw_item(
            raw,
            category_map=_category_map(configs),
            category_rules=configs["category_rules"],
            source_overrides=configs.get("source_category_overrides", {}),
            source_native_taxonomy=configs.get("source_native_taxonomy", {}),
        )
        primary_category = classification.primary_category
        category_bucket = classification.category_bucket

        published_at = str(raw.get("published_at", "")).strip()
        hours_ago = _hours_ago_from_iso(published_at)
        source_meta = source_index.get(source_id, {})
        dimensions = _infer_dimensions(
            source_meta=source_meta,
            category_bucket=category_bucket,
            hours_ago=hours_ago,
            text=text,
        )
        attrs = _infer_attributes(category_bucket, text, cluster_rules)

        digest = hashlib.md5(f"{source_id}|{title}|{published_at}".encode("utf-8")).hexdigest()[:10]
        item = CandidateItem(
            id=f"ingest-{source_id}-{digest}",
            title=title,
            summary=summary or title,
            source_id=source_id,
            published_hours_ago=hours_ago,
            primary_category=primary_category if primary_category in category_keys else category_keys[0],
            secondary_tags=classification.secondary_tags,
            event_key=slugify_event_key(title, cluster_rules),
            dimensions=dimensions,
            attributes=attrs,
            source_url=str(raw.get("source_url", "")).strip(),
            canonical_url=str(raw.get("canonical_url", "")).strip(),
        )
        items.append(item)

    return items


def prefilter_items(
    items: list[CandidateItem],
    watchlists: dict[str, Any],
) -> tuple[list[CandidateItem], list[CandidateItem]]:
    terms = {
        term.lower()
        for bucket in watchlists["watchlists"].values()
        for term in bucket
    }
    kept: list[CandidateItem] = []
    rejected: list[CandidateItem] = []
    for item in items:
        text = f"{item.title} {item.summary}".lower()
        if item.primary_category or any(term.lower() in text for term in terms):
            kept.append(item)
        else:
            rejected.append(item)
    return kept, rejected


def _weighted_dimension_score(dimensions: dict[str, float], scoring: dict[str, Any]) -> float:
    total = 0.0
    aliases = scoring.get("dimension_aliases", {})
    scale = scoring.get("base_score", {}).get("scale_per_point", 20)
    for key, weight in scoring["model_dimensions"].items():
        value = dimensions.get(key, 0)
        if value == 0:
            for legacy_key, mapped_key in aliases.items():
                if mapped_key == key and legacy_key in dimensions:
                    value = dimensions.get(legacy_key, 0)
                    break
        total += value * scale * weight
    return total


def _source_adjustment(source_meta: dict[str, Any], scoring: dict[str, Any]) -> int:
    tier = source_meta.get("tier", "T2")
    group = source_meta.get("group", "media")
    role = source_meta.get("role", "discovery_and_context")
    tier_bonus = scoring["source_adjustments"]["tier_weights"].get(tier, 0)
    group_bonus = scoring["source_adjustments"]["group_adjustments"].get(group, 0)
    role_bonus = scoring["source_adjustments"].get("role_adjustments", {}).get(role, 0)
    return int(tier_bonus + group_bonus + role_bonus)


def _recency_adjustment(hours_ago: int, scoring: dict[str, Any]) -> int:
    recency = scoring["recency_adjustments"]
    if hours_ago <= 6:
        return int(recency["within_6h"])
    if hours_ago <= 24:
        return int(recency["within_24h"])
    if hours_ago <= 48:
        return int(recency["older_than_24h"])
    return int(recency["older_than_48h"])


def _investor_focus_adjustment(item: CandidateItem, scoring: dict[str, Any]) -> int:
    rules = scoring["investor_focus_adjustments"]
    bonus = 0
    if item.attributes.get("exit_environment"):
        bonus += int(rules["exit_environment_bonus"])
    if item.attributes.get("deal_activity"):
        bonus += int(rules["deal_activity_bonus"])
    if item.attributes.get("sector_structure"):
        bonus += int(rules["sector_structure_bonus"])
    if item.attributes.get("policy_shock"):
        bonus += int(rules["policy_shock_bonus"])
    if item.attributes.get("cross_asset"):
        bonus += int(rules["cross_asset_bonus"])
    if item.attributes.get("commentary_only"):
        bonus += int(rules["commentary_only_penalty"])
    if item.attributes.get("narrow_single_company"):
        bonus += int(rules["narrow_single_company_penalty"])
    return bonus


def _apply_normalization(total: float, scoring: dict[str, Any]) -> int:
    normalization = scoring.get("normalization", {})
    scale_min = int(normalization.get("scale_min", 0))
    scale_max = int(normalization.get("scale_max", 100))
    soft_cap_start = float(normalization.get("soft_cap_start", scale_max))
    soft_cap_factor = float(normalization.get("soft_cap_factor", 1.0))

    adjusted = total
    if adjusted > soft_cap_start:
        adjusted = soft_cap_start + (adjusted - soft_cap_start) * soft_cap_factor

    rounded = round(adjusted)
    return max(scale_min, min(scale_max, rounded))


def score_items(items: list[CandidateItem], configs: dict[str, Any]) -> list[CandidateItem]:
    scoring = configs["scoring"]
    source_index = build_source_index(configs["sources"])
    for item in items:
        source_meta = source_index.get(item.source_id, {})
        base = _weighted_dimension_score(item.dimensions, scoring)
        source_adj = _source_adjustment(source_meta, scoring)
        category_adj = int(scoring["category_adjustments"].get(item.primary_category, 0))
        recency_adj = _recency_adjustment(item.published_hours_ago, scoring)
        investor_adj = _investor_focus_adjustment(item, scoring)
        total = base + source_adj + category_adj + recency_adj + investor_adj
        item.final_score = _apply_normalization(total, scoring)
    return items


def apply_cluster_adjustments(clusters: list[EventCluster], configs: dict[str, Any]) -> None:
    scoring = configs["scoring"]["event_adjustments"]
    for cluster in clusters:
        cluster.primary_item.final_score = min(
            100,
            cluster.primary_item.final_score + int(scoring["primary_item_bonus"]),
        )
        for item in cluster.related_items:
            item.final_score = max(0, item.final_score + int(scoring["duplicate_penalty"]))


def select_items(clusters: list[EventCluster], configs: dict[str, Any]) -> list[CandidateItem]:
    thresholds = configs["thresholds"]
    source_index = build_source_index(configs["sources"])
    category_caps = thresholds["output_limits"]["category_caps"]
    selected: list[CandidateItem] = []
    per_category: dict[str, int] = defaultdict(int)

    ranked_primary_items = sorted(
        [cluster.primary_item for cluster in clusters],
        key=lambda item: item.final_score,
        reverse=True,
    )

    for item in ranked_primary_items:
        source_meta = source_index.get(item.source_id, {})
        base_threshold = thresholds["selection_thresholds"].get(item.primary_category, 65)
        tier = source_meta.get("tier", "T2")
        threshold_delta = thresholds["source_overrides"].get(tier, {}).get("threshold_delta", 0)
        threshold = base_threshold + threshold_delta + thresholds["cluster_overrides"]["primary_item_delta"]
        if item.final_score < threshold:
            continue
        if per_category[item.primary_category] >= category_caps.get(item.primary_category, 99):
            continue
        selected.append(item)
        per_category[item.primary_category] += 1

    total_cap = thresholds["output_limits"]["total_items_max"]
    return selected[:total_cap]


def _ordered_categories(configs: dict[str, Any]) -> list[str]:
    configured = list(configs["thresholds"]["selection_thresholds"].keys())
    preferred = [
        "地缘政治",
        "宏观经济",
        "政策监管",
        "产业趋势",
        "科技进展",
        "资本市场与交易",
        "风险事件",
    ]
    return preferred if all(category in configured for category in preferred) else configured


def _preferred_url(item: CandidateItem) -> str:
    return item.canonical_url or item.source_url


def render_newsletter(items: list[CandidateItem], now_date: str) -> str:
    grouped: dict[str, list[CandidateItem]] = defaultdict(list)
    for item in items:
        grouped[item.primary_category].append(item)

    ordered_categories = [
        "地缘政治",
        "宏观经济",
        "政策监管",
        "产业趋势",
        "科技进展",
        "资本市场与交易",
        "风险事件",
    ]

    lines = [f"# {now_date} Daily Newsletter"]

    for category in ordered_categories:
        bucket = grouped.get(category)
        if not bucket:
            continue
        lines.extend(["", f"## {category}"])
        for idx, item in enumerate(sorted(bucket, key=lambda x: x.final_score, reverse=True), start=1):
            lines.append(f"### {idx}. {item.title}")
            lines.append(f"- Why it matters: {item.summary}")
            lines.append(f"- Facts: source=`{item.source_id}`; hours_ago={item.published_hours_ago}")
            lines.append(f"- Data: dimensions={item.dimensions}")
            lines.append(f"- New: primary cluster item={item.cluster_primary}; merged_reports={item.merged_reports}")
            lines.append(
                "- Take: This item passed the current category threshold and remained after de-duplication."
            )
            lines.append(f"- Sources: {_preferred_url(item)}")

    return "\n".join(lines)


def render_candidate_pool(result: PipelineResult, configs: dict[str, Any], now_date: str) -> str:
    selected_ids = {item.id for item in result.selected_items}
    clusters_by_category: dict[str, list[EventCluster]] = defaultdict(list)
    for cluster in result.clusters:
        clusters_by_category[cluster.primary_item.primary_category].append(cluster)

    lines = [
        f"# {now_date} Daily Newsletter Candidate Pool",
        "",
        "## Summary",
        f"- Raw items: {len(result.raw_items)}",
        f"- Passed prefilter: {len(result.filtered_items)}",
        f"- Rejected at prefilter: {len(result.rejected_items)}",
        f"- Event clusters: {len(result.clusters)}",
        f"- Selected primary items: {len(result.selected_items)}",
    ]

    for category in _ordered_categories(configs):
        bucket = clusters_by_category.get(category)
        if not bucket:
            continue
        lines.extend(["", f"## {category}"])
        ranked_bucket = sorted(
            bucket,
            key=lambda cluster: (
                cluster.primary_item.id not in selected_ids,
                -cluster.primary_item.final_score,
                cluster.primary_item.published_hours_ago,
            ),
        )
        for idx, cluster in enumerate(ranked_bucket, start=1):
            item = cluster.primary_item
            status = "selected" if item.id in selected_ids else "not_selected"
            lines.append(f"### {idx}. {item.title}")
            lines.append(f"- Status: {status} / primary")
            lines.append(
                f"- Internal: score={item.final_score}; source=`{item.source_id}`; "
                f"hours_ago={item.published_hours_ago}; merged_reports={item.merged_reports}; "
                f"event_key=`{item.event_key or item.id}`"
            )
            lines.append(f"- Summary: {item.summary}")
            lines.append(f"- Tags: {', '.join(item.secondary_tags) if item.secondary_tags else 'None'}")
            lines.append(f"- Source link: {_preferred_url(item)}")
            if cluster.related_items:
                lines.append("- Related reports:")
                for related in sorted(cluster.related_items, key=lambda x: x.final_score, reverse=True):
                    related_status = "selected" if related.id in selected_ids else "not_selected"
                    merge_reason = cluster.related_merge_reasons.get(related.id, "same_event")
                    merge_confidence = cluster.related_merge_confidences.get(related.id, 0.0)
                    lines.append(
                        f"  - {related.title} | {related_status} / related | "
                        f"score={related.final_score} | source=`{related.source_id}` | "
                        f"hours_ago={related.published_hours_ago} | "
                        f"merge={merge_reason} ({merge_confidence}) | {_preferred_url(related)}"
                    )

    if result.rejected_items:
        lines.extend(["", "## 预筛淘汰"])
        for idx, item in enumerate(result.rejected_items, start=1):
            lines.append(f"### {idx}. {item.title}")
            lines.append("- Status: rejected_at_prefilter")
            lines.append(f"- Internal: source=`{item.source_id}`; hours_ago={item.published_hours_ago}")
            lines.append(f"- Summary: {item.summary}")
            lines.append(f"- Source link: {_preferred_url(item)}")

    return "\n".join(lines)


def run_pipeline(items: list[CandidateItem], configs: dict[str, Any]) -> PipelineResult:
    filtered, rejected = prefilter_items(items, configs["watchlists"])
    scored = score_items(filtered, configs)
    clusters = cluster_items(scored, configs)
    apply_cluster_adjustments(clusters, configs)
    selected = select_items(clusters, configs)
    return PipelineResult(
        raw_items=list(items),
        filtered_items=filtered,
        rejected_items=rejected,
        scored_items=scored,
        clusters=clusters,
        selected_items=selected,
    )
