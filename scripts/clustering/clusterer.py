from __future__ import annotations

from typing import Any

from clustering.explain import merge_confidence, merge_reason
from clustering.models import ClusterDecision
from clustering.rules import (
    clustering_rules,
    generate_cluster_key,
    same_event_decision,
    source_priority,
)
from pipeline_models import CandidateItem, EventCluster


def _build_source_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for source in config["sources"]:
        index[source["id"]] = source
        for alias in source.get("aliases", []):
            index[alias] = source
    return index


def cluster_items(items: list[CandidateItem], configs: dict[str, Any]) -> list[EventCluster]:
    source_index = _build_source_index(configs["sources"])
    rules = clustering_rules(configs)
    clusters: list[EventCluster] = []
    merge_decisions: dict[tuple[str, str], ClusterDecision] = {}
    sorted_items = sorted(
        items,
        key=lambda item: (item.primary_category, item.published_hours_ago, item.id),
    )

    cluster_members: list[list[CandidateItem]] = []
    for item in sorted_items:
        matched_bucket: list[CandidateItem] | None = None
        for bucket in cluster_members:
            for existing in bucket:
                decision = same_event_decision(item, existing, source_index, rules)
                if decision.should_merge:
                    matched_bucket = bucket
                    merge_decisions[(item.id, existing.id)] = decision
                    break
            if matched_bucket is not None:
                break
        if matched_bucket is None:
            cluster_members.append([item])
        else:
            matched_bucket.append(item)

    for members in cluster_members:
        primary = sorted(
            members,
            key=lambda item: source_priority(item, source_index),
            reverse=True,
        )[0]
        cluster_key = generate_cluster_key(primary, members, rules)
        for member in members:
            member.event_key = cluster_key
            member.cluster_primary = member.id == primary.id
            member.merged_reports = max(len(members) - 1, 0)
        primary.cluster_primary = True
        related = [item for item in members if item.id != primary.id]
        related_reasons: dict[str, str] = {}
        related_confidences: dict[str, float] = {}
        for related_item in related:
            decisions = [
                decision
                for member in members
                if member.id != related_item.id
                for decision in (
                    merge_decisions.get((related_item.id, member.id))
                    or merge_decisions.get((member.id, related_item.id)),
                )
                if decision is not None
            ]
            if decisions:
                best = sorted(decisions, key=lambda decision: decision.confidence, reverse=True)[0]
                related_reasons[related_item.id] = merge_reason(best)
                related_confidences[related_item.id] = merge_confidence(best)
        clusters.append(
            EventCluster(
                event_key=cluster_key,
                primary_item=primary,
                related_items=related,
                related_merge_reasons=related_reasons,
                related_merge_confidences=related_confidences,
            )
        )
    return clusters
