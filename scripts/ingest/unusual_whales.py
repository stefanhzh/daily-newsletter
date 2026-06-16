#!/usr/bin/env python3
"""Unusual Whales News ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.parse import urljoin

from .base import BaseAdapter, IngestedItem, dedupe_items, extract_meta_content


class UnusualWhalesAdapter(BaseAdapter):
    source_id = "unusual-whales"
    news_url = "https://unusualwhales.com/news"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.news_url)
        except Exception:
            return []

        payload = self._extract_next_data(html)
        if not payload:
            return []

        collected: list[IngestedItem] = []
        page_props = payload.get("props", {}).get("pageProps", {})
        groups = [
            ("featured", page_props.get("featuredArticles", [])),
            ("research", page_props.get("researchPosts", [])),
            ("education", page_props.get("educationalPosts", [])),
        ]
        for section_name, rows in groups:
            for row in rows[:30]:
                item = self._row_to_item(row, section_name)
                if item is not None:
                    collected.append(item)
        return dedupe_items(collected)

    def _extract_next_data(self, html: str) -> dict[str, object]:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return {}
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}

    def _row_to_item(self, row: dict[str, object], section_name: str) -> IngestedItem | None:
        title = self.clean_text(str(row.get("title", "")))
        slug = str(row.get("slug", "")).strip()
        created_at = str(row.get("created_at", "")).strip()
        tags = row.get("tags", [])
        if not title or not slug or not created_at:
            return None

        try:
            published_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        canonical_url = urljoin("https://unusualwhales.com", f"/news/{slug}")
        summary = self._fetch_summary(canonical_url)
        if not summary and isinstance(tags, list):
            summary = self.clean_text("Tags: " + ", ".join(str(tag) for tag in tags if str(tag).strip()))

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=canonical_url,
            canonical_url=canonical_url,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline="Unusual Whales",
            section=section_name,
            discovery_method="unusualwhales_next_data",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _fetch_summary(self, url: str) -> str:
        try:
            html = self.request_text(url)
        except Exception:
            return ""
        summary = extract_meta_content(html, "og:description") or extract_meta_content(html, "description")
        return self.clean_text(summary)
