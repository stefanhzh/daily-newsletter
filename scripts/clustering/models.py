from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterDecision:
    should_merge: bool
    reason: str = ""
    confidence: float = 0.0
