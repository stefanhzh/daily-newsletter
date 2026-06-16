#!/usr/bin/env python3
"""Build the first clean candidate pool and review pack."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.registry import ADAPTERS, build_adapters  # noqa: E402
from ingest.base import IngestedItem, dedupe_items  # noqa: E402


TIER_WEIGHTS = {
    "T1": 1.2,
    "T1_5": 1.05,
    "T2": 0.9,
}

ROLE_TOP_K = {
    "primary_news": 20,
    "wire": 15,
    "official": 10,
    "social_trend": 10,
    "market_trend": 20,
    "technical_trend": 15,
    "watchlist": 20,
    "discovery": 10,
}

COVERAGE_EXPANSION_QUOTAS = {
    "geopolitics": 40,
    "technology": 40,
    "industry": 30,
    "risk": 25,
    "policy": 20,
    "macro": 15,
}

EXPANSION_SOURCE_ROLE_LIMITS = {
    "primary_news": 8,
    "wire": 8,
    "official": 6,
    "discovery": 8,
    "social_trend": 6,
    "market_trend": 6,
    "technical_trend": 8,
    "watchlist": 5,
}

SOURCE_TOP_K_OVERRIDES = {
    "wsj": 20,
    "wall-street-journal": 20,
}

SOURCE_SECTION_PRIORITIES = {
    "cailian": {
        "hot_article": 0,
        "top_article": 1,
        "depth_list": 2,
    },
    "techcrunch": {
        "top_headlines": 0,
        "most_popular": 1,
        "latest": 2,
    },
    "bbc": {
        "homepage_ranked": 0,
    },
    "caixin": {
        "homepage_ranked": 0,
    },
    "cnbc": {
        "homepage_ranked": 0,
    },
    "semafor": {
        "homepage_ranked": 0,
    },
    "ths-hotrank": {
        "headline": 0,
        "important_flash": 1,
        "finance_news": 2,
        "stock_news": 3,
        "sector_rank": 4,
        "flash": 5,
        "commodity_market": 6,
    },
    "zerohedge": {
        "homepage_ranked": 0,
    },
}

SURFACE_WEIGHTS = {
    "homepage": 1.0,
    "frontpage": 1.0,
    "top-news": 0.95,
    "hot": 0.95,
    "popular": 0.9,
    "trending": 0.9,
    "rss": 0.72,
    "feed": 0.72,
    "search": 0.62,
    "profile": 0.55,
    "keyword": 0.55,
}

NOISE_PATTERNS = [
    r"\badvertisement\b",
    r"\bsponsored\b",
    r"\bsubscribe now\b",
    r"\bnewsletter signup\b",
    r"\bwatch live\b",
    r"\blive updates\b",
    r"\bphoto gallery\b",
    r"\bvideo:\b",
    r"\bhow to watch\b",
    r"\bdaily horoscope\b",
    r"\bwordle\b",
    r"\bsudoku\b",
]

SECTION_KEYWORDS = {
    "geopolitics": [
        "tariff",
        "sanction",
        "export control",
        "china",
        "russia",
        "ukraine",
        "israel",
        "iran",
        "trump",
        "xi",
        "beijing",
        "war",
        "ceasefire",
        "中美",
        "关税",
        "制裁",
        "外交",
        "俄乌",
    ],
    "macro": [
        "fed",
        "inflation",
        "cpi",
        "ppi",
        "gdp",
        "yield",
        "treasury",
        "rate cut",
        "central bank",
        "央行",
        "通胀",
        "利率",
        "降息",
        "经济",
    ],
    "policy": [
        "regulation",
        "regulator",
        "ministry",
        "antitrust",
        "lawmakers",
        "senate",
        "监管",
        "政策",
        "证监会",
        "商务部",
    ],
    "industry": [
        "supply chain",
        "automaker",
        "energy",
        "shipping",
        "semiconductor",
        "产业",
        "供应链",
        "新能源",
        "汽车",
        "芯片",
    ],
    "technology": [
        "ai",
        "artificial intelligence",
        "openai",
        "anthropic",
        "nvidia",
        "model",
        "robot",
        "github",
        "人工智能",
        "大模型",
        "算力",
    ],
    "markets": [
        "stock",
        "shares",
        "earnings",
        "ipo",
        "bond",
        "fund",
        "bitcoin",
        "crypto",
        "美股",
        "港股",
        "a股",
        "财报",
        "上市",
    ],
    "risk": [
        "lawsuit",
        "default",
        "bankruptcy",
        "crash",
        "fraud",
        "investigation",
        "风险",
        "破产",
        "调查",
        "事故",
    ],
}


@dataclass
class SourcePolicy:
    source_id: str
    adapter_id: str
    source_name: str
    source_tier: str
    source_group: str
    source_role: str
    fetch_method: str
    top_k: int
    formal_status: str
    notes: str = ""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def load_sources_config() -> dict[str, Any]:
    path = ROOT / "config" / "sources.json"
    return load_json(path)


def source_to_adapter_id(source: dict[str, Any]) -> str | None:
    candidates = [source.get("id", "")] + source.get("aliases", [])
    for candidate in candidates:
        if candidate in ADAPTERS:
            return candidate
    return None


def role_for_source(source_id: str, group: str, role: str, fetch_method: str) -> str:
    text = " ".join([source_id, group, role, fetch_method]).lower()
    if any(token in text for token in ["hot", "trend", "trending", "rank", "popular"]):
        if any(token in text for token in ["github", "technical", "developer"]):
            return "technical_trend"
        if any(token in text for token in ["market", "stock", "ths"]):
            return "market_trend"
        return "social_trend"
    if group in {"official", "regulator", "exchange"}:
        return "official"
    if group == "wire":
        return "wire"
    if group in {"social", "kol"}:
        return "watchlist"
    if role in {"directed_monitoring", "discovery_only"}:
        return "discovery"
    return "primary_news"


def infer_policy_for_adapter(adapter_id: str) -> SourcePolicy:
    social = {
        "x-account-posts",
        "tiktok-profile-signals",
        "zhihu-hot",
        "xiaohongshu-search",
        "bilibili-popular",
        "youtube-channel-feeds",
        "reddit-hot",
        "wechat-search",
        "xiaoyuzhou-feeds",
    }
    trend = {
        "google-trends",
        "github-trending",
        "github-issues-trends",
        "ths-hotrank",
    }
    if adapter_id in social:
        role = "social_trend" if adapter_id.endswith(("hot", "popular", "search")) else "watchlist"
        top_k = ROLE_TOP_K.get(role, 10)
        if adapter_id in {"x-account-posts", "tiktok-profile-signals"}:
            top_k = 8
        return SourcePolicy(
            source_id=adapter_id,
            adapter_id=adapter_id,
            source_name=adapter_id.replace("-", " ").title(),
            source_tier="T2",
            source_group="social",
            source_role=role,
            fetch_method="adapter_only",
            top_k=top_k,
            formal_status="adapter_only_missing_sources_json",
            notes="Has adapter but is not yet formalized in config/sources.json.",
        )
    if adapter_id in trend:
        role = "technical_trend" if "github" in adapter_id else "market_trend"
        return SourcePolicy(
            source_id=adapter_id,
            adapter_id=adapter_id,
            source_name=adapter_id.replace("-", " ").title(),
            source_tier="T2",
            source_group="trend",
            source_role=role,
            fetch_method="adapter_only",
            top_k=ROLE_TOP_K.get(role, 10),
            formal_status="adapter_only_missing_sources_json",
            notes="Trend/rank source with adapter-level policy.",
        )
    return SourcePolicy(
        source_id=adapter_id,
        adapter_id=adapter_id,
        source_name=adapter_id.replace("-", " ").title(),
        source_tier="T2",
        source_group="unknown",
        source_role="discovery",
        fetch_method="adapter_only",
        top_k=8,
        formal_status="adapter_only_missing_sources_json",
        notes="Needs source catalog review.",
    )


def build_source_policies() -> tuple[dict[str, SourcePolicy], list[dict[str, Any]]]:
    config = load_sources_config()
    policies: dict[str, SourcePolicy] = {}
    catalog_rows: list[dict[str, Any]] = []
    adapter_ids_used: set[str] = set()

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        adapter_id = source_to_adapter_id(source)
        source_id = source.get("id", "")
        row = {
            "source_id": source_id,
            "source_name": source.get("name", source_id),
            "formal_status": "formal_with_adapter" if adapter_id else "formal_missing_adapter",
            "adapter_id": adapter_id or "",
            "tier": source.get("tier", "T2"),
            "group": source.get("group", ""),
            "role": source.get("role", ""),
            "fetch_method": source.get("fetch_method", ""),
        }
        catalog_rows.append(row)
        if not adapter_id:
            continue
        role = role_for_source(
            source_id,
            source.get("group", ""),
            source.get("role", ""),
            source.get("fetch_method", ""),
        )
        top_k = ROLE_TOP_K.get(role, 10)
        top_k = SOURCE_TOP_K_OVERRIDES.get(source_id, SOURCE_TOP_K_OVERRIDES.get(adapter_id, top_k))
        actual_source_id = getattr(ADAPTERS[adapter_id], "source_id", "")
        policies[adapter_id] = SourcePolicy(
            source_id=source_id,
            adapter_id=adapter_id,
            source_name=source.get("name", source_id),
            source_tier=source.get("tier", "T2"),
            source_group=source.get("group", ""),
            source_role=role,
            fetch_method=source.get("fetch_method", ""),
            top_k=top_k,
            formal_status="formal_with_adapter",
            notes=source.get("notes", ""),
        )
        if actual_source_id and actual_source_id != adapter_id:
            policies[actual_source_id] = policies[adapter_id]
        adapter_ids_used.add(adapter_id)

    alias_adapter_ids = {
        alias
        for source in config.get("sources", [])
        for alias in source.get("aliases", [])
        if source_to_adapter_id(source)
    }
    for adapter_id in sorted(ADAPTERS):
        if adapter_id in adapter_ids_used or adapter_id in alias_adapter_ids:
            continue
        policy = infer_policy_for_adapter(adapter_id)
        policies[adapter_id] = policy
        catalog_rows.append(asdict(policy))

    return policies, catalog_rows


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def candidate_id(item: IngestedItem) -> str:
    raw = f"{item.source_id}|{item.canonical_url or item.source_url}|{item.title}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def title_key(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", value)
    return value.strip()


def discovery_surface(item: IngestedItem) -> str:
    text = " ".join([item.discovery_method, item.rank_section, item.section]).lower()
    for key in SURFACE_WEIGHTS:
        if key in text:
            return key
    if item.rank_position:
        return "ranked_list"
    return "feed"


def rank_signal_score(item: IngestedItem, policy: SourcePolicy) -> float:
    source_weight = TIER_WEIGHTS.get(policy.source_tier, 0.9)
    surface = discovery_surface(item)
    surface_weight = SURFACE_WEIGHTS.get(surface, 0.7)
    if item.rank_position and item.rank_position > 0:
        position_score = max(0.15, 1.0 - ((item.rank_position - 1) * 0.075))
    else:
        position_score = 0.55
    return round(min(1.0, source_weight * surface_weight * position_score / 1.2), 3)


def freshness_score(item: IngestedItem, now: datetime) -> float:
    parsed = parse_datetime(item.published_at)
    if not parsed:
        return 0.35
    hours = max(0.0, (now - parsed).total_seconds() / 3600)
    return round(max(0.05, 1.0 - (hours / 36)), 3)


def soft_tags(text: str) -> dict[str, float]:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for section, keywords in SECTION_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword_matches(lowered, keyword))
        if hits:
            scores[section] = round(min(1.0, 0.35 + hits * 0.18), 3)
    return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True))


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    keyword = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&-]*", keyword):
        pattern = r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
        return bool(re.search(pattern, lowered_text))
    return keyword in lowered_text


def extract_entities(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.\-]{2,}(?:\s+[A-Z][A-Za-z0-9&.\-]{2,}){0,3}\b", text)
    cn_candidates = re.findall(r"[\u4e00-\u9fff]{2,8}(?:公司|集团|银行|证券|科技|汽车|基金|交易所|委员会|部门)", text)
    merged: list[str] = []
    for value in candidates + cn_candidates:
        value = value.strip()
        if value and value not in merged and value.lower() not in {"the", "and", "for"}:
            merged.append(value)
        if len(merged) >= 8:
            break
    return merged


def noise_flags(item: IngestedItem, policy: SourcePolicy) -> list[str]:
    flags: list[str] = []
    title = item.title.strip()
    url = item.canonical_url or item.source_url
    searchable = f"{title} {item.summary} {item.section} {item.rank_section}".lower()
    if len(title) < 8:
        flags.append("title_too_short")
    if not url:
        flags.append("missing_url")
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, searchable, re.IGNORECASE):
            flags.append(f"pattern:{pattern}")
            break
    if policy.source_role in {"social_trend", "watchlist"} and not item.rank_position and len(item.summary) < 30:
        flags.append("weak_social_signal")
    if item.fulltext_status == "metadata_only" and policy.source_role not in {"social_trend", "watchlist"}:
        flags.append("metadata_only_non_social")
    return flags


def keep_reason(item: IngestedItem, policy: SourcePolicy, rank_score: float, fresh_score: float) -> str:
    parts = [policy.source_tier, policy.source_role]
    if item.rank_position:
        parts.append(f"rank #{item.rank_position}")
    if rank_score >= 0.75:
        parts.append("strong rank signal")
    if fresh_score >= 0.75:
        parts.append("fresh")
    if item.fulltext_status == "full_text_capable":
        parts.append("fulltext capable")
    return ", ".join(parts)


def top_soft_tag(tags: dict[str, float]) -> str:
    if not tags:
        return ""
    return max(tags.items(), key=lambda item: item[1])[0]


def item_sort_key(item: IngestedItem) -> tuple[int, int, str]:
    section_priority = SOURCE_SECTION_PRIORITIES.get(item.source_id, {}).get(
        item.rank_section or item.section,
        50,
    )
    rank = item.rank_position if item.rank_position else 9999
    return (section_priority, rank, item.published_at or "")


def fetch_raw_items(source_ids: list[str], lookback_hours: int) -> tuple[list[IngestedItem], dict[str, str], Counter[str]]:
    raw_items: list[IngestedItem] = []
    failures: dict[str, str] = {}
    raw_counts: Counter[str] = Counter()
    for adapter in build_adapters(source_ids, lookback_hours=lookback_hours):
        try:
            adapter_items = adapter.fetch()
        except Exception as exc:  # noqa: BLE001
            failures[adapter.source_id] = exc.__class__.__name__
            continue
        raw_items.extend(adapter_items)
        raw_counts[adapter.source_id] += len(adapter_items)
    return dedupe_items(raw_items), failures, raw_counts


def load_raw_items(path: Path) -> tuple[list[IngestedItem], Counter[str]]:
    payload = load_json(path)
    items = [IngestedItem(**item) for item in payload]
    counts: Counter[str] = Counter()
    for item in items:
        counts[item.source_id] += 1
    return dedupe_items(items), counts


def build_candidates(raw_items: list[IngestedItem], policies: dict[str, SourcePolicy]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    now = datetime.now(timezone.utc)
    grouped: dict[str, list[IngestedItem]] = defaultdict(list)
    for item in raw_items:
        grouped[item.source_id].append(item)

    clean_candidates: list[dict[str, Any]] = []
    dropped_samples: list[dict[str, Any]] = []
    clean_counts: Counter[str] = Counter()
    seen_urls: set[str] = set()
    seen_source_titles: set[tuple[str, str]] = set()
    expansion_pool: list[dict[str, Any]] = []

    for source_id, items in grouped.items():
        policy = policies.get(source_id) or infer_policy_for_adapter(source_id)
        source_kept = 0
        for item in sorted(items, key=item_sort_key):
            flags = noise_flags(item, policy)
            canonical_url = item.canonical_url or item.source_url
            duplicate_title = title_key(item.title)
            source_title_key = (source_id, duplicate_title)
            if canonical_url and canonical_url in seen_urls:
                flags.append("duplicate_url")
            if duplicate_title and source_title_key in seen_source_titles:
                flags.append("duplicate_title_same_source")
            rank_score = rank_signal_score(item, policy)
            fresh_score = freshness_score(item, now)
            text = " ".join([item.title, item.summary, item.body_text])
            tags = soft_tags(text)
            should_keep = not flags and source_kept < policy.top_k
            record = {
                "candidate_id": candidate_id(item),
                "source_id": source_id,
                "source_name": policy.source_name,
                "source_tier": policy.source_tier,
                "source_group": policy.source_group,
                "source_role": policy.source_role,
                "formal_status": policy.formal_status,
                "title": item.title,
                "url": item.source_url,
                "canonical_url": canonical_url,
                "published_at": item.published_at,
                "byline": item.byline,
                "section": item.section,
                "summary": item.summary,
                "body_text_available": bool(item.body_text.strip()),
                "discovery_method": item.discovery_method,
                "discovery_surface": discovery_surface(item),
                "rank_position": item.rank_position,
                "rank_section": item.rank_section,
                "fulltext_status": item.fulltext_status,
                "fulltext_note": item.fulltext_note,
                "source_weight": TIER_WEIGHTS.get(policy.source_tier, 0.9),
                "rank_signal_score": rank_score,
                "freshness_score": fresh_score,
                "entities": extract_entities(text),
                "soft_tags": tags,
                "keep": should_keep,
                "keep_reason": keep_reason(item, policy, rank_score, fresh_score) if should_keep else "",
                "selection_stage": "source_top_k" if should_keep else "",
                "coverage_reason": "",
                "noise_flags": flags,
                "review_status": "unreviewed",
            }
            if should_keep:
                clean_candidates.append(record)
                clean_counts[source_id] += 1
                source_kept += 1
                if canonical_url:
                    seen_urls.add(canonical_url)
                if duplicate_title:
                    seen_source_titles.add(source_title_key)
            elif not flags:
                record["keep_reason"] = "eligible_for_coverage_expansion"
                record["selection_stage"] = "coverage_candidate"
                expansion_pool.append(record)
            elif len(dropped_samples) < 80 and flags:
                dropped_samples.append(record)

    expansion_candidates = select_coverage_expansion(expansion_pool, clean_candidates, seen_urls)
    for candidate in expansion_candidates:
        clean_candidates.append(candidate)
        clean_counts[candidate["source_id"]] += 1
        canonical_url = candidate.get("canonical_url", "")
        if canonical_url:
            seen_urls.add(canonical_url)

    clean_candidates.sort(
        key=lambda row: (
            row["source_role"],
            row["source_id"],
            row["rank_position"] or 9999,
            -row["rank_signal_score"],
        )
    )
    return clean_candidates, dropped_samples, clean_counts


def select_coverage_expansion(
    expansion_pool: list[dict[str, Any]],
    existing_candidates: list[dict[str, Any]],
    seen_urls: set[str],
) -> list[dict[str, Any]]:
    existing_by_section: Counter[str] = Counter()
    for candidate in existing_candidates:
        section = top_soft_tag(candidate.get("soft_tags", {}))
        if section:
            existing_by_section[section] += 1

    picked: list[dict[str, Any]] = []
    picked_by_source_role: Counter[tuple[str, str]] = Counter()
    picked_urls: set[str] = set()
    pool = sorted(
        expansion_pool,
        key=lambda row: (
            -(row.get("rank_signal_score") or 0),
            -(row.get("freshness_score") or 0),
            row.get("rank_position") or 9999,
        ),
    )

    for section, target in COVERAGE_EXPANSION_QUOTAS.items():
        if existing_by_section.get(section, 0) >= target:
            continue
        needed = target - existing_by_section.get(section, 0)
        section_picks = 0
        for candidate in pool:
            if section_picks >= needed:
                break
            if candidate.get("selection_stage") == "coverage_expansion":
                continue
            if top_soft_tag(candidate.get("soft_tags", {})) != section:
                continue
            canonical_url = candidate.get("canonical_url", "")
            if canonical_url and (canonical_url in seen_urls or canonical_url in picked_urls):
                continue
            source_role = candidate.get("source_role", "")
            role_key = (section, source_role)
            role_limit = EXPANSION_SOURCE_ROLE_LIMITS.get(source_role, 6)
            if picked_by_source_role[role_key] >= role_limit:
                continue

            selected = dict(candidate)
            selected["keep"] = True
            selected["selection_stage"] = "coverage_expansion"
            selected["coverage_reason"] = f"{section}_quota_fill"
            selected["keep_reason"] = f"coverage expansion: {section} quota fill"
            picked.append(selected)
            picked_by_source_role[role_key] += 1
            section_picks += 1
            existing_by_section[section] += 1
            if canonical_url:
                picked_urls.add(canonical_url)

    return picked


def render_review_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = payload["run_meta"]
    lines.append(f"# Clean Candidates Review - {meta['generated_at']}")
    lines.append("")
    lines.append("## Run Summary")
    lines.append(f"- Window: past {meta['window_hours']}h")
    lines.append(f"- Sources requested: {meta['source_count']}")
    lines.append(f"- Raw candidates: {meta['raw_count']}")
    lines.append(f"- Clean candidates: {meta['clean_count']}")
    lines.append(f"- Dropped samples shown: {len(payload['dropped_samples'])}")
    lines.append("")
    lines.append("## Source Summary")
    lines.append("| Source | Role | Status | Raw | Clean | Top K | Notes |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for source in payload["source_summaries"]:
        lines.append(
            "| {source_name} (`{source_id}`) | {source_role} | {status} | {raw_count} | {clean_count} | {top_k} | {notes} |".format(
                **source
            )
        )
    lines.append("")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in payload["candidates"]:
        grouped[candidate["source_id"]].append(candidate)

    lines.append("## Candidates By Source")
    for source_id, candidates in grouped.items():
        source_name = candidates[0]["source_name"]
        lines.append("")
        lines.append(f"### {source_name} (`{source_id}`)")
        for idx, candidate in enumerate(candidates, start=1):
            title = candidate["title"].replace("\n", " ").strip()
            lines.append("")
            lines.append(f"#### {idx}. {title}")
            lines.append(f"- Candidate ID: `{candidate['candidate_id']}`")
            lines.append(f"- URL: {candidate['canonical_url']}")
            lines.append(f"- Published: {candidate['published_at'] or 'unknown'}")
            rank = candidate["rank_position"] or "n/a"
            lines.append(f"- Rank: {candidate['rank_section'] or candidate['discovery_surface']} #{rank}")
            lines.append(f"- Selection: {candidate.get('selection_stage') or 'unknown'} {candidate.get('coverage_reason') or ''}".rstrip())
            lines.append(
                "- Signals: source_weight={source_weight}, rank={rank_signal_score}, freshness={freshness_score}".format(
                    **candidate
                )
            )
            if candidate["soft_tags"]:
                tag_text = ", ".join(f"{key}={value}" for key, value in candidate["soft_tags"].items())
                lines.append(f"- Soft tags: {tag_text}")
            if candidate["entities"]:
                lines.append(f"- Entities: {', '.join(candidate['entities'])}")
            lines.append(f"- Keep reason: {candidate['keep_reason']}")
            summary = candidate["summary"].replace("\n", " ").strip()
            if summary:
                lines.append(f"- Summary: {summary[:420]}")
            lines.append("- Review: `[ ] KEEP` `[ ] DROP` `[ ] DUPLICATE` `[ ] WRONG_SECTION` `[ ] SCORE_TOO_HIGH` `[ ] SCORE_TOO_LOW`")
            lines.append("- Merge with:")
            lines.append("- Notes:")

    lines.append("")
    lines.append("## Dropped / Borderline Samples")
    for candidate in payload["dropped_samples"][:40]:
        lines.append("")
        lines.append(f"### {candidate['title']}")
        lines.append(f"- Source: {candidate['source_name']} (`{candidate['source_id']}`)")
        lines.append(f"- URL: {candidate['canonical_url']}")
        lines.append(f"- Drop flags: {', '.join(candidate['noise_flags'])}")
        lines.append("- Review: `[ ] SHOULD_KEEP` `[ ] CORRECTLY_DROPPED`")
    lines.append("")
    return "\n".join(lines)


def source_summaries(
    policies: dict[str, SourcePolicy],
    requested_sources: list[str],
    raw_counts: Counter[str],
    clean_counts: Counter[str],
    failures: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_id in requested_sources:
        policy = policies.get(source_id) or infer_policy_for_adapter(source_id)
        adapter_cls = ADAPTERS.get(source_id)
        actual_source_id = getattr(adapter_cls, "source_id", source_id) if adapter_cls else source_id
        status = "failed" if source_id in failures else "ok"
        notes = failures.get(source_id, policy.notes)
        rows.append(
            {
                "source_id": source_id,
                "source_name": policy.source_name,
                "source_role": policy.source_role,
                "formal_status": policy.formal_status,
                "status": status,
                "raw_count": raw_counts.get(source_id, raw_counts.get(actual_source_id, 0)),
                "clean_count": clean_counts.get(source_id, clean_counts.get(actual_source_id, 0)),
                "top_k": policy.top_k,
                "notes": (notes or "").replace("|", "/")[:160],
            }
        )
    return rows


def default_source_ids(policies: dict[str, SourcePolicy]) -> list[str]:
    ids = []
    for source_id, policy in policies.items():
        if source_id in {"wsj"}:
            continue
        ids.append(source_id)
    return sorted(dict.fromkeys(ids))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build clean candidates and a human review pack.")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--sources", nargs="+", help="Adapter source IDs to run. Defaults to current adapter-backed catalog.")
    parser.add_argument("--output-json", type=Path, default=ROOT / "data" / "clean_candidates_24h.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "data" / "review_candidates_24h.md")
    parser.add_argument("--raw-output", type=Path, default=ROOT / "data" / "raw_candidates_24h.json")
    parser.add_argument("--input-raw", type=Path, help="Reuse an existing raw candidate JSON instead of fetching sources.")
    args = parser.parse_args()

    policies, catalog_rows = build_source_policies()
    requested_sources = args.sources or default_source_ids(policies)
    if args.input_raw:
        raw_items, raw_counts = load_raw_items(args.input_raw)
        failures: dict[str, str] = {}
        if not args.sources:
            requested_sources = sorted(raw_counts)
    else:
        raw_items, failures, raw_counts = fetch_raw_items(requested_sources, args.lookback_hours)
    clean_candidates, dropped_samples, clean_counts = build_candidates(raw_items, policies)

    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload = {
        "run_meta": {
            "run_id": generated_at.replace(":", "-"),
            "generated_at": generated_at,
            "window_hours": args.lookback_hours,
            "source_count": len(requested_sources),
            "raw_count": len(raw_items),
            "clean_count": len(clean_candidates),
            "failed_source_count": len(failures),
        },
        "source_catalog": catalog_rows,
        "source_summaries": source_summaries(policies, requested_sources, raw_counts, clean_counts, failures),
        "candidates": clean_candidates,
        "dropped_samples": dropped_samples,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_review_markdown(payload), encoding="utf-8")
    if not args.input_raw:
        args.raw_output.write_text(
            json.dumps([item.to_dict() for item in raw_items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    print(f"raw_output={args.raw_output}")
    print(f"source_count={len(requested_sources)}")
    print(f"raw_count={len(raw_items)}")
    print(f"clean_count={len(clean_candidates)}")
    if failures:
        print(f"failed_sources={len(failures)}")
        for source_id, reason in sorted(failures.items()):
            print(f"{source_id}={reason}")


if __name__ == "__main__":
    main()
