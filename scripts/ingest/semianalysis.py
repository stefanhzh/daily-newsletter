#!/usr/bin/env python3
"""SemiAnalysis ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import re

from .base import BaseAdapter, IngestedItem, dedupe_items


class SemianalysisAdapter(BaseAdapter):
    source_id = "semianalysis"
    api_url = "https://newsletter.semianalysis.com/api/v1/archive?sort=new&limit=30"

    def fetch(self) -> list[IngestedItem]:
        try:
            payload = self.request_text(self.api_url)
            rows = json.loads(payload)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            item = self._row_to_item(row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _row_to_item(self, row: dict[str, object]) -> IngestedItem | None:
        link = str(row.get("canonical_url", "")).strip()
        raw_date = str(row.get("post_date", "")).strip()
        title = self._normalize_text(str(row.get("title", "")).strip())
        summary = self._build_summary(row)
        if not link or not raw_date or not title:
            return None

        try:
            published_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline="SemiAnalysis",
            section="latest",
            discovery_method="semianalysis_substack_api",
            body_text="",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _build_summary(self, row: dict[str, object]) -> str:
        candidates = [
            str(row.get("truncated_body_text", "")).strip(),
            str(row.get("subtitle", "")).strip(),
            str(row.get("description", "")).strip(),
        ]
        for value in candidates:
            normalized = self._normalize_text(value)
            if normalized:
                return normalized
        return ""

    def _normalize_text(self, value: str) -> str:
        replacements = {
            "бк": "—",
            "鈥攂": "—",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        value = re.sub(r"\s+", " ", unescape(value or "")).strip()
        return value
