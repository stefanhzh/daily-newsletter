#!/usr/bin/env python3
"""Score a classified candidate pool with 50-point rules and 50-point model scoring."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from pipeline import load_configs, load_items_from_path, run_pipeline  # noqa: E402
from scoring.scorer import score_candidate_clusters  # noqa: E402


DEFAULT_PROMPT = ROOT / "config" / "model_scoring_prompt.md"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Path to adapter raw_items.json.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "scoring")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "reports" / "scoring" / "model_cache")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model-mode", choices=["llm", "heuristic"], default="llm")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--limit-model-calls",
        type=int,
        default=0,
        help="If >0, run real model scoring for only the first N pipeline-ranked clusters; remaining clusters use heuristic fallback.",
    )
    args = parser.parse_args()

    raw_items = json.loads(args.input.read_text(encoding="utf-8"))
    source_summary = _load_source_summary(args.input)
    configs = load_configs()
    items = load_items_from_path(args.input, configs)
    result = run_pipeline(items, configs)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_dir = args.output_dir / stamp
    cache_dir = args.cache_dir

    scored = score_candidate_clusters(
        result.clusters,
        raw_items=raw_items,
        configs=configs,
        prompt_path=args.prompt,
        cache_dir=cache_dir,
        model_mode=args.model_mode,
        model=args.model or None,
        limit_model_calls=args.limit_model_calls or None,
    )

    payload: dict[str, Any] = {
        "run_meta": {
            "input": str(args.input),
            "prompt": str(args.prompt),
            "model_mode": args.model_mode,
            "model": args.model or None,
            "limit_model_calls": args.limit_model_calls,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "summary": {
            "raw_item_count": len(raw_items),
            "normalized_item_count": len(items),
            "filtered_item_count": len(result.filtered_items),
            "rejected_item_count": len(result.rejected_items),
            "cluster_count": len(result.clusters),
            "selected_count_legacy_pipeline": len(result.selected_items),
            "normalized_category_distribution": dict(Counter(item.primary_category for item in items)),
            "filtered_category_distribution": dict(Counter(item.primary_category for item in result.filtered_items)),
            "category_distribution": dict(Counter(cluster.primary_item.primary_category for cluster in result.clusters)),
            "source_distribution": dict(Counter(item.source_id for item in result.filtered_items)),
            "score_distribution": _score_distribution([item.ranking_score for item in scored]),
        },
        "source_summaries": source_summary,
        "clusters": [item.to_dict() for item in scored],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "scored_candidate_pool.json"
    md_path = output_dir / "scored_candidate_pool.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


def _score_distribution(scores: list[float]) -> dict[str, float | None]:
    if not scores:
        return {"min": None, "max": None, "avg": None}
    return {
        "min": round(min(scores), 2),
        "max": round(max(scores), 2),
        "avg": round(sum(scores) / len(scores), 2),
    }


def _load_source_summary(input_path: Path) -> list[dict[str, Any]]:
    summary_path = input_path.parent / "source_summary.json"
    if not summary_path.exists():
        return []
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    return list(payload.get("source_summaries") or [])


def _format_counter(counter: dict[str, int], *, limit: int | None = None) -> list[str]:
    items = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    if limit is not None:
        items = items[:limit]
    return [f"- {key or 'unknown'}: {value}" for key, value in items]


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    source_summaries = payload.get("source_summaries") or []
    source_failures = [
        source
        for source in source_summaries
        if source.get("status") != "ok" or int(source.get("output_count") or 0) == 0
    ]
    lines = [
        "# Scored Candidate Pool",
        "",
        "## Summary",
        f"- Input: `{payload['run_meta']['input']}`",
        f"- Model mode: `{payload['run_meta']['model_mode']}`",
        f"- Prompt: `{payload['run_meta']['prompt']}`",
        f"- Raw items: {summary['raw_item_count']}",
        f"- Normalized items: {summary['normalized_item_count']}",
        f"- Filtered items: {summary['filtered_item_count']}",
        f"- Rejected items: {summary['rejected_item_count']}",
        f"- Event clusters: {summary['cluster_count']}",
        f"- Legacy selected count: {summary['selected_count_legacy_pipeline']}",
        f"- Ranking score distribution: {summary['score_distribution']}",
        "",
        "## Pipeline Stages",
        "- Ingest: adapter raw items are loaded from `raw_items.json`.",
        "- Classification: `pipeline.load_items_from_path()` normalizes adapter items and calls the existing classification rules.",
        "- Filtering: existing relevance and source-native noise filters run before scoring.",
        "- Clustering: existing `clustering.clusterer.cluster_items()` merges related reports into event clusters.",
        "- Scoring: this report ranks clusters with 50-point rule scoring plus 50-point model scoring.",
        "",
        "## Classification Distribution",
        "",
        "### Normalized Items",
        *_format_counter(summary["normalized_category_distribution"]),
        "",
        "### Filtered Items",
        *_format_counter(summary["filtered_category_distribution"]),
        "",
        "### Event Clusters",
        *_format_counter(summary["category_distribution"]),
        "",
        "## Source Coverage",
        *_format_counter(summary["source_distribution"], limit=40),
        "",
        "## Source Gaps",
        *(
            [
                f"- {source.get('source_id')}: status={source.get('status')}; fetched={source.get('raw_count')}; shown={source.get('output_count')}; error={source.get('error') or ''}"
                for source in source_failures
            ]
            or ["- None"]
        ),
        "",
        "## Top Ranked Clusters",
    ]
    for idx, item in enumerate(payload["clusters"][:100], start=1):
        rule = item["rule_score"]
        model = item["model_score"]
        lines.extend(
            [
                "",
                f"### {idx}. {item['primary_title']}",
                f"- Ranking score: {item['ranking_score']:.2f} = rule {rule['total']:.2f} + model {model['total']:.2f}",
                f"- Category: {item['primary_category']}; source=`{item['source_id']}`; related={item['related_count']}",
                f"- Summary: {item['summary']}",
                f"- Rule: platform={rule['platform_score']:.2f}; rank={rule['rank_score']:.2f}",
                f"- Platform reason: {rule['platform_reason']}",
                f"- Rank reason: {rule['rank_reason']}",
                f"- Model relevance: {model['relevance_score_1_to_5']:.2f}/5; mode=`{model['mode']}`",
                f"- Action: {model['action_recommendation']}",
                f"- URL: {item['url']}",
            ]
        )
        if item["related_reports"]:
            lines.append("- Related reports:")
            for related in item["related_reports"]:
                lines.append(
                    f"  - {related['title']} | source=`{related['source_id']}` | legacy_score={related['score']} | {related['url']}"
                )
    lines.extend(["", "## Top By Category"])
    clusters_by_category: dict[str, list[dict[str, Any]]] = {}
    for item in payload["clusters"]:
        clusters_by_category.setdefault(item["primary_category"], []).append(item)
    for category in sorted(clusters_by_category):
        lines.extend(["", f"### {category}"])
        for item in clusters_by_category[category][:10]:
            lines.append(
                f"- {item['ranking_score']:.2f} | {item['source_id']} | {item['primary_title']}"
            )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
