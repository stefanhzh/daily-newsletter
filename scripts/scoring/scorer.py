from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline_models import EventCluster

from .model_score import score_cluster_with_model
from .models import ScoredCluster
from .rule_score import build_raw_meta_index, build_source_index, score_cluster_rules


def score_candidate_clusters(
    clusters: list[EventCluster],
    *,
    raw_items: list[dict[str, Any]],
    configs: dict[str, Any],
    prompt_path: Path,
    cache_dir: Path,
    model_mode: str,
    model: str | None = None,
    limit_model_calls: int | None = None,
) -> list[ScoredCluster]:
    source_index = build_source_index(configs["sources"])
    raw_meta_index = build_raw_meta_index(raw_items)
    sorted_clusters = sorted(
        clusters,
        key=lambda cluster: cluster.primary_item.final_score,
        reverse=True,
    )
    scored: list[ScoredCluster] = []
    for idx, cluster in enumerate(sorted_clusters):
        rule_score = score_cluster_rules(
            cluster,
            source_index=source_index,
            raw_meta_index=raw_meta_index,
        )
        if limit_model_calls is not None and idx >= limit_model_calls:
            model_mode_for_item = "heuristic"
        else:
            model_mode_for_item = model_mode
        model_score = score_cluster_with_model(
            cluster,
            prompt_path=prompt_path,
            raw_meta_index=raw_meta_index,
            cache_dir=cache_dir,
            model=model,
            mode=model_mode_for_item,
        )
        ranking_score = round(rule_score.total + model_score.total, 2)
        primary = cluster.primary_item
        scored.append(
            ScoredCluster(
                event_key=cluster.event_key,
                primary_item_id=primary.id,
                primary_title=primary.title,
                primary_category=primary.primary_category,
                source_id=primary.source_id,
                url=primary.canonical_url or primary.source_url,
                related_count=len(cluster.related_items),
                summary=primary.summary,
                related_reports=[
                    {
                        "title": item.title,
                        "source_id": item.source_id,
                        "score": item.final_score,
                        "url": item.canonical_url or item.source_url,
                    }
                    for item in sorted(cluster.related_items, key=lambda item: item.final_score, reverse=True)
                ],
                rule_score=rule_score,
                model_score=model_score,
                ranking_score=ranking_score,
            )
        )
    return sorted(scored, key=lambda item: item.ranking_score, reverse=True)
