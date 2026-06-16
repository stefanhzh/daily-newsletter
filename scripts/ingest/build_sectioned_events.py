#!/usr/bin/env python3
"""Classify event clusters into newsletter sections for review."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


NEWSLETTER_SECTIONS = [
    "地缘政治与全球秩序",
    "宏观经济与政策",
    "产业与公司",
    "科技与 AI",
    "资本市场与交易",
    "风险事件",
    "趋势与社媒信号",
]

INTERNAL_SECTION_MAP = {
    "geopolitics": "地缘政治与全球秩序",
    "macro": "宏观经济与政策",
    "policy": "宏观经济与政策",
    "industry": "产业与公司",
    "technology": "科技与 AI",
    "markets": "资本市场与交易",
    "risk": "风险事件",
}

TREND_SOURCE_ROLES = {"social_trend", "market_trend", "technical_trend", "watchlist"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def event_section(cluster: dict[str, Any]) -> tuple[str, str]:
    item_roles = {item.get("source_role", "") for item in cluster.get("items", [])}
    if item_roles and item_roles <= TREND_SOURCE_ROLES:
        return "趋势与社媒信号", "all_items_are_trend_or_watchlist_sources"

    section = cluster.get("candidate_section", "")
    mapped = INTERNAL_SECTION_MAP.get(section)
    if mapped:
        return mapped, f"mapped_from_{section}"

    tag_scores: Counter[str] = Counter()
    for item in cluster.get("items", []):
        for tag, score in (item.get("soft_tags") or {}).items():
            tag_scores[tag] += float(score)
    if tag_scores:
        best = tag_scores.most_common(1)[0][0]
        mapped = INTERNAL_SECTION_MAP.get(best)
        if mapped:
            return mapped, f"highest_soft_tag_{best}"

    if any(role in TREND_SOURCE_ROLES for role in item_roles):
        return "趋势与社媒信号", "contains_trend_or_watchlist_source"
    return "产业与公司", "fallback_uncategorized_to_industry_company"


def section_score(cluster: dict[str, Any]) -> float:
    source_count = cluster.get("source_count", 1)
    item_count = cluster.get("item_count", 1)
    source_bonus = min(0.25, max(0, source_count - 1) * 0.06)
    item_bonus = min(0.12, max(0, item_count - 1) * 0.03)
    rank_signal = float(cluster.get("rank_signal_score") or 0)
    freshness = float(cluster.get("freshness_score") or 0)
    main_tier = cluster.get("main_source_tier", "T2")
    tier_bonus = {"T1": 0.18, "T1_5": 0.1, "T2": 0.04}.get(main_tier, 0)
    expansion_penalty = 0.03 if any(
        item.get("selection_stage") == "coverage_expansion"
        for item in cluster.get("items", [])
    ) and source_count == 1 else 0
    score = (rank_signal * 0.38) + (freshness * 0.22) + source_bonus + item_bonus + tier_bonus - expansion_penalty
    return round(max(0.0, min(1.0, score)), 3)


def build_sectioned_payload(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    sections: dict[str, list[dict[str, Any]]] = {section: [] for section in NEWSLETTER_SECTIONS}
    for cluster in clusters:
        section, reason = event_section(cluster)
        row = dict(cluster)
        row["newsletter_section"] = section
        row["section_reason"] = reason
        row["section_score"] = section_score(cluster)
        row["section_review_status"] = "unreviewed"
        sections[section].append(row)

    for section, events in sections.items():
        events.sort(
            key=lambda event: (
                -event["section_score"],
                -event["source_count"],
                -event["rank_signal_score"],
                event["main_title"],
            )
        )
    return {"sections": sections}


def render_review_markdown(payload: dict[str, Any]) -> str:
    meta = payload["run_meta"]
    lines: list[str] = []
    lines.append(f"# Sectioned Events Review - {meta['generated_at']}")
    lines.append("")
    lines.append("## Run Summary")
    lines.append(f"- Input clusters: {meta['input_cluster_count']}")
    lines.append(f"- Sections: {len(NEWSLETTER_SECTIONS)}")
    lines.append("")
    lines.append("## Section Counts")
    lines.append("| Section | Events |")
    lines.append("|---|---:|")
    for section in NEWSLETTER_SECTIONS:
        lines.append(f"| {section} | {len(payload['sections'][section])} |")
    lines.append("")
    lines.append("## Review Guide")
    lines.append("- `KEEP`: suitable for this section candidate pool.")
    lines.append("- `DROP`: should not enter later scoring.")
    lines.append("- `MOVE_SECTION`: belongs in another section.")
    lines.append("- `MERGE_OR_SPLIT`: cluster structure needs adjustment.")
    lines.append("- `BOOST` / `LOWER`: rough importance feels too low/high.")
    lines.append("")

    for section in NEWSLETTER_SECTIONS:
        events = payload["sections"][section]
        lines.append(f"## {section}")
        if not events:
            lines.append("")
            lines.append("_No events._")
            lines.append("")
            continue
        for idx, event in enumerate(events[:45], start=1):
            lines.append("")
            lines.append(f"### {idx}. {event['main_title']}")
            lines.append(f"- Event ID: `{event['event_id']}`")
            lines.append(f"- Score: {event['section_score']} | Reason: {event['section_reason']}")
            lines.append(f"- Main: {event['main_source_name']} (`{event['main_source']}`, {event['main_source_tier']})")
            lines.append(f"- Sources: {', '.join(event['sources'])} | Items: {event['item_count']}")
            lines.append(f"- URL: {event['main_url']}")
            if event.get("entities"):
                lines.append(f"- Entities: {', '.join(event['entities'][:8])}")
            expansion_count = sum(1 for item in event.get("items", []) if item.get("selection_stage") == "coverage_expansion")
            if expansion_count:
                lines.append(f"- Coverage expansion items: {expansion_count}")
            lines.append("- Review: `[ ] KEEP` `[ ] DROP` `[ ] MOVE_SECTION` `[ ] MERGE_OR_SPLIT` `[ ] BOOST` `[ ] LOWER`")
            lines.append("- Notes:")
        if len(events) > 45:
            lines.append("")
            lines.append(f"_Hidden from review view: {len(events) - 45} lower-ranked events._")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify event clusters into newsletter sections for review.")
    parser.add_argument("--input-json", type=Path, default=ROOT / "data" / "event_clusters_24h.json")
    parser.add_argument("--output-json", type=Path, default=ROOT / "data" / "sectioned_events_24h.json")
    parser.add_argument("--output-md", type=Path, default=ROOT / "data" / "review_sections_24h.md")
    args = parser.parse_args()

    input_payload = load_json(args.input_json)
    clusters = input_payload.get("clusters", input_payload if isinstance(input_payload, list) else [])
    sectioned = build_sectioned_payload(clusters)

    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload = {
        "run_meta": {
            "run_id": generated_at.replace(":", "-"),
            "generated_at": generated_at,
            "input_path": str(args.input_json),
            "input_cluster_count": len(clusters),
        },
        **sectioned,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_review_markdown(payload), encoding="utf-8")

    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    print(f"input_cluster_count={len(clusters)}")
    for section in NEWSLETTER_SECTIONS:
        print(f"{section}={len(payload['sections'][section])}")


if __name__ == "__main__":
    main()
