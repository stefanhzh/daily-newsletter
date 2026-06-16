from __future__ import annotations

from clustering.models import ClusterDecision


def merge_reason(decision: ClusterDecision) -> str:
    return decision.reason or "same_event"


def merge_confidence(decision: ClusterDecision) -> float:
    return decision.confidence
