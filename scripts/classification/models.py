#!/usr/bin/env python3
"""Small classification data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClassificationResult:
    primary_category: str
    category_bucket: str
    secondary_tags: list[str]
    classification_source: str
    classification_reason: str
    classification_text: str
    scores: dict[str, int] = field(default_factory=dict)

