#!/usr/bin/env python3
"""Build conservative event clusters from clean candidates."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.build_clean_candidates import build_source_policies, parse_datetime  # noqa: E402


TIER_RANK = {
    "T1": 0,
    "T1_5": 1,
    "T2": 2,
}

GROUP_RANK = {
    "official": 0,
    "regulator": 0,
    "exchange": 0,
    "wire": 1,
    "media": 2,
    "sector_media": 3,
    "technical_platform": 4,
    "trend": 5,
    "social": 6,
    "kol": 7,
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "after",
    "over",
    "into",
    "what",
    "why",
    "how",
    "new",
    "latest",
    "news",
    "says",
    "said",
    "report",
    "reports",
    "update",
    "updates",
    "live",
    "breaking",
}


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def clean_title(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\s*[-|_]\s*(reuters|ap|bbc|cnbc|financial times|wsj|wall street journal|caixin|bloomberg)\s*$", "", value)
    value = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩\d.\s、:：-]+", "", value)
    value = re.sub(r"\b(live updates?|breaking|exclusive|analysis|opinion)\b", " ", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def title_tokens(value: str) -> set[str]:
    normalized = clean_title(value)
    latin = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", normalized)
        if token not in STOPWORDS
    }
    chinese_chunks = set(re.findall(r"[\u4e00-\u9fff]{2,8}", normalized))
    return latin | chinese_chunks


def canonical_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def same_domain(left: str, right: str) -> bool:
    left_host = urlsplit(left or "").netloc.lower().removeprefix("www.")
    right_host = urlsplit(right or "").netloc.lower().removeprefix("www.")
    return bool(left_host and left_host == right_host)


def top_soft_tag(candidate: dict[str, Any]) -> str:
    tags = candidate.get("soft_tags") or {}
    if not tags:
        return ""
    return max(tags.items(), key=lambda item: item[1])[0]


def time_gap_hours(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_dt = parse_datetime(left.get("published_at", ""))
    right_dt = parse_datetime(right.get("published_at", ""))
    if not left_dt or not right_dt:
        return 999.0
    return abs((left_dt - right_dt).total_seconds()) / 3600


def title_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    return SequenceMatcher(None, clean_title(left.get("title", "")), clean_title(right.get("title", ""))).ratio()


def token_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = title_tokens(" ".join([left.get("title", ""), left.get("summary", "")]))
    right_tokens = title_tokens(" ".join([right.get("title", ""), right.get("summary", "")]))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def entity_overlap(left: dict[str, Any], right: dict[str, Any]) -> int:
    left_entities = {str(value).lower() for value in left.get("entities", []) if value}
    right_entities = {str(value).lower() for value in right.get("entities", []) if value}
    return len(left_entities & right_entities)


def merge_decision(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, str, float]:
    left_url = canonical_url(left.get("canonical_url") or left.get("url", ""))
    right_url = canonical_url(right.get("canonical_url") or right.get("url", ""))
    same_source = left.get("source_id") == right.get("source_id")
    similarity = title_similarity(left, right)
    if left_url and right_url and left_url == right_url:
        if same_source and similarity < 0.8:
            return False, "", 0.0
        return True, "same_canonical_url", 1.0

    left_title = clean_title(left.get("title", ""))
    right_title = clean_title(right.get("title", ""))
    if left_title and right_title and left_title == right_title:
        return True, "same_normalized_title", 0.98

    if same_source:
        if similarity >= 0.9:
            return True, "same_source_high_title_similarity", round(similarity, 3)
        return False, "", 0.0

    gap = time_gap_hours(left, right)
    if gap > 48:
        return False, "", 0.0

    overlap = token_overlap(left, right)
    shared_entities = entity_overlap(left, right)
    same_section = top_soft_tag(left) and top_soft_tag(left) == top_soft_tag(right)

    if similarity >= 0.88:
        return True, "high_title_similarity", round(similarity, 3)

    if same_domain(left_url, right_url) and similarity >= 0.78:
        return True, "same_domain_title_similarity", round(similarity, 3)

    if shared_entities >= 2 and overlap >= 0.5 and same_section:
        confidence = min(0.9, 0.58 + shared_entities * 0.08 + overlap * 0.2)
        return True, "entities_tokens_section_match", round(confidence, 3)

    if overlap >= 0.72 and similarity >= 0.55 and same_section:
        return True, "strong_token_overlap", round(min(0.86, overlap), 3)

    return False, "", 0.0


def current_source_policy(candidate: dict[str, Any], policies: dict[str, Any]) -> dict[str, str]:
    source_id = candidate.get("source_id", "")
    policy = policies.get(source_id)
    if not policy:
        return {
            "source_tier": candidate.get("source_tier", "T2"),
            "source_group": candidate.get("source_group", ""),
            "source_name": candidate.get("source_name", source_id),
        }
    return {
        "source_tier": policy.source_tier,
        "source_group": policy.source_group,
        "source_name": policy.source_name,
    }


def main_item_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    current_tier = candidate.get("current_source_tier") or candidate.get("source_tier", "T2")
    current_group = candidate.get("current_source_group") or candidate.get("source_group", "")
    rank_position = candidate.get("rank_position") or 9999
    rank_signal = candidate.get("rank_signal_score") or 0
    freshness = candidate.get("freshness_score") or 0
    summary_len = len(candidate.get("summary") or "")
    return (
        TIER_RANK.get(current_tier, 9),
        GROUP_RANK.get(current_group, 8),
        rank_position,
        -rank_signal,
        -freshness,
        -summary_len,
    )


def cluster_id_for(items: list[dict[str, Any]]) -> str:
    seed = "|".join(sorted(item["candidate_id"] for item in items))
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]


def cluster_section(items: list[dict[str, Any]]) -> str:
    scores: Counter[str] = Counter()
    for item in items:
        for tag, score in (item.get("soft_tags") or {}).items():
            scores[tag] += float(score)
    if not scores:
        return "uncategorized"
    return scores.most_common(1)[0][0]


def cluster_entities(items: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    original: dict[str, str] = {}
    for item in items:
        for entity in item.get("entities", []):
            key = str(entity).lower()
            counts[key] += 1
            original.setdefault(key, str(entity))
    return [original[key] for key, _ in counts.most_common(10)]


def cluster_merge_reason(item_indices: list[int], merge_reasons: dict[tuple[int, int], tuple[str, float]]) -> tuple[str, float]:
    reasons: Counter[str] = Counter()
    confidences: list[float] = []
    item_set = set(item_indices)
    for (left, right), (reason, confidence) in merge_reasons.items():
        if left in item_set and right in item_set:
            reasons[reason] += 1
            confidences.append(confidence)
    if not reasons:
        return "single_item", 1.0
    reason = reasons.most_common(1)[0][0]
    return reason, round(sum(confidences) / len(confidences), 3)


def build_clusters(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    union = UnionFind(len(candidates))
    merge_reasons: dict[tuple[int, int], tuple[str, float]] = {}
    for left_idx in range(len(candidates)):
        for right_idx in range(left_idx + 1, len(candidates)):
            should_merge, reason, confidence = merge_decision(candidates[left_idx], candidates[right_idx])
            if should_merge:
                union.union(left_idx, right_idx)
                merge_reasons[(left_idx, right_idx)] = (reason, confidence)

    grouped: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(candidates)):
        grouped[union.find(idx)].append(idx)

    clusters: list[dict[str, Any]] = []
    for indices in grouped.values():
        items = [candidates[idx] for idx in indices]
        items.sort(key=main_item_sort_key)
        main = items[0]
        reason, confidence = cluster_merge_reason(indices, merge_reasons)
        sources = sorted({item["source_id"] for item in items})
        clusters.append(
            {
                "event_id": cluster_id_for(items),
                "main_title": main["title"],
                "main_url": main.get("canonical_url") or main.get("url", ""),
                "main_source": main["source_id"],
                "main_source_name": main.get("current_source_name") or main.get("source_name", ""),
                "main_source_tier": main.get("current_source_tier") or main.get("source_tier", ""),
                "published_at": main.get("published_at", ""),
                "candidate_section": cluster_section(items),
                "sources": sources,
                "source_count": len(sources),
                "item_count": len(items),
                "entities": cluster_entities(items),
                "merge_confidence": confidence,
                "merge_reason": reason,
                "rank_signal_score": max((item.get("rank_signal_score") or 0) for item in items),
                "freshness_score": max((item.get("freshness_score") or 0) for item in items),
                "items": items,
                "review_status": "unreviewed",
            }
        )

    clusters.sort(
        key=lambda cluster: (
            -cluster["source_count"],
            TIER_RANK.get(cluster["main_source_tier"], 9),
            -cluster["rank_signal_score"],
            -cluster["freshness_score"],
            cluster["main_title"],
        )
    )
    return clusters


def enrich_candidates_with_current_policy(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    policies, _ = build_source_policies()
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        updated = dict(candidate)
        policy = current_source_policy(candidate, policies)
        updated["current_source_tier"] = policy["source_tier"]
        updated["current_source_group"] = policy["source_group"]
        updated["current_source_name"] = policy["source_name"]
        enriched.append(updated)
    return enriched


def render_review_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = payload["run_meta"]
    lines.append(f"# Event Clusters Review - {meta['generated_at']}")
    lines.append("")
    lines.append("## Run Summary")
    lines.append(f"- Input candidates: {meta['input_candidate_count']}")
    lines.append(f"- Event clusters: {meta['cluster_count']}")
    lines.append(f"- Multi-item clusters: {meta['multi_item_cluster_count']}")
    lines.append(f"- Multi-source clusters: {meta['multi_source_cluster_count']}")
    lines.append("")
    lines.append("## Review Guide")
    lines.append("- `OK`: cluster is correctly merged.")
    lines.append("- `SPLIT`: cluster merges unrelated events.")
    lines.append("- `MERGE_WITH_OTHER`: this event should merge with another event ID.")
    lines.append("- `WRONG_MAIN`: cluster is right, but the main item should be another source/item.")
    lines.append("- `WRONG_SECTION`: event section is wrong.")
    lines.append("")

    for idx, cluster in enumerate(payload["clusters"], start=1):
        lines.append(f"## {idx}. {cluster['main_title']}")
        lines.append(f"- Event ID: `{cluster['event_id']}`")
        lines.append(f"- Main: {cluster['main_source_name']} (`{cluster['main_source']}`, {cluster['main_source_tier']})")
        lines.append(f"- URL: {cluster['main_url']}")
        lines.append(f"- Section: `{cluster['candidate_section']}`")
        lines.append(f"- Sources: {', '.join(cluster['sources'])}")
        lines.append(f"- Items: {cluster['item_count']} | Source count: {cluster['source_count']}")
        lines.append(f"- Merge: {cluster['merge_reason']} / confidence={cluster['merge_confidence']}")
        if cluster["entities"]:
            lines.append(f"- Entities: {', '.join(cluster['entities'])}")
        lines.append("- Review: `[ ] OK` `[ ] SPLIT` `[ ] MERGE_WITH_OTHER` `[ ] WRONG_MAIN` `[ ] WRONG_SECTION`")
        lines.append("- Notes:")
        lines.append("")
        for item_idx, item in enumerate(cluster["items"], start=1):
            rank = item.get("rank_position") or "n/a"
            tier = item.get("current_source_tier") or item.get("source_tier")
            lines.append(
                f"  {item_idx}. `{item['source_id']}` {tier} rank={rank} "
                f"[{item['title']}]({item.get('canonical_url') or item.get('url', '')})"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build conservative event clusters from clean candidates.")
    parser.add_argument("--input-json", type=Path, default=ROOT / "data" / "clean_candidates_24h.json")
    parser.add_argument("--output-json", type=Path, default=ROOT / "data" / "event_clusters_24h.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "data" / "review_events_24h.md")
    args = parser.parse_args()

    input_payload = load_json(args.input_json)
    candidates = input_payload.get("candidates", input_payload if isinstance(input_payload, list) else [])
    candidates = [candidate for candidate in candidates if candidate.get("keep", True)]
    enriched_candidates = enrich_candidates_with_current_policy(candidates)
    clusters = build_clusters(enriched_candidates)

    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload = {
        "run_meta": {
            "run_id": generated_at.replace(":", "-"),
            "generated_at": generated_at,
            "input_path": str(args.input_json),
            "input_candidate_count": len(candidates),
            "cluster_count": len(clusters),
            "multi_item_cluster_count": sum(1 for cluster in clusters if cluster["item_count"] > 1),
            "multi_source_cluster_count": sum(1 for cluster in clusters if cluster["source_count"] > 1),
        },
        "clusters": clusters,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_review_markdown(payload), encoding="utf-8")

    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    print(f"input_candidate_count={len(candidates)}")
    print(f"cluster_count={len(clusters)}")
    print(f"multi_item_cluster_count={payload['run_meta']['multi_item_cluster_count']}")
    print(f"multi_source_cluster_count={payload['run_meta']['multi_source_cluster_count']}")


if __name__ == "__main__":
    main()
