#!/usr/bin/env python3
"""Human-readable classification explanations."""

from __future__ import annotations

from .models import ClassificationResult


def explain_classification(result: ClassificationResult) -> str:
    if result.classification_reason:
        return result.classification_reason
    return f"{result.classification_source}:{result.category_bucket}"

