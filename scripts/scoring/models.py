from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawItemMeta:
    source_id: str = ""
    title: str = ""
    rank_section: str = ""
    rank_position: int | None = None
    discovery_method: str = ""
    source_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleScore:
    platform_score: float
    rank_score: float
    total: float
    platform_reason: str
    rank_reason: str


@dataclass(frozen=True)
class ModelScore:
    total: float
    relevance_score_1_to_5: float
    expert_views: list[dict[str, str]]
    action_recommendation: str
    mode: str
    raw_response: str = ""


@dataclass(frozen=True)
class ScoredCluster:
    event_key: str
    primary_item_id: str
    primary_title: str
    primary_category: str
    source_id: str
    url: str
    related_count: int
    summary: str
    related_reports: list[dict[str, Any]]
    rule_score: RuleScore
    model_score: ModelScore
    ranking_score: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ranking_score"] = round(self.ranking_score, 2)
        return payload
