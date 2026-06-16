from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CandidateItem:
    id: str
    title: str
    summary: str
    source_id: str
    published_hours_ago: int
    primary_category: str
    secondary_tags: list[str]
    event_key: str
    dimensions: dict[str, float]
    attributes: dict[str, Any]
    source_url: str
    canonical_url: str = ""
    final_score: int = 0
    cluster_primary: bool = False
    merged_reports: int = 0


@dataclass
class EventCluster:
    event_key: str
    primary_item: CandidateItem
    related_items: list[CandidateItem] = field(default_factory=list)
    related_merge_reasons: dict[str, str] = field(default_factory=dict)
    related_merge_confidences: dict[str, float] = field(default_factory=dict)


@dataclass
class PipelineResult:
    raw_items: list[CandidateItem]
    filtered_items: list[CandidateItem]
    rejected_items: list[CandidateItem]
    scored_items: list[CandidateItem]
    clusters: list[EventCluster]
    selected_items: list[CandidateItem]
