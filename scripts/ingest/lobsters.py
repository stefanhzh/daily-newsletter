#!/usr/bin/env python3
"""Lobsters ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import re

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class LobstersAdapter(BaseAdapter):
    source_id = "lobsters"
    feed_url = "https://lobste.rs/newest.rss"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for entry in parse_rss_items(xml_text)[:60]:
            item = self._entry_to_item(entry)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _entry_to_item(self, entry: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        source_url = entry.get("link", "").strip()
        raw_pub_date = entry.get("pubDate", "").strip()
        guid = entry.get("guid", "").strip()
        description_html = entry.get("description", "") or ""
        if not title or not source_url or not raw_pub_date:
            return None

        try:
            published_at = self.normalize_published_at(raw_pub_date)
        except Exception:
            return None
        if not self.within_lookback(datetime.fromisoformat(published_at)):
            return None

        canonical_url = self._extract_comments_url(description_html) or guid or source_url
        summary = (
            "Lobsters discussion thread for an external article. "
            "External link preserved in source_url; canonical_url points to the discussion page."
        )

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=source_url,
            canonical_url=canonical_url,
            published_at=published_at,
            summary=summary,
            byline="Lobsters",
            section="newest",
            discovery_method="lobsters_rss",
            fulltext_note="discussion_page_comments",
        )

    def _extract_comments_url(self, html_snippet: str) -> str:
        match = re.search(r'href="(https://lobste\.rs/s/[^"]+)"', html_snippet or "", re.I)
        return match.group(1).strip() if match else ""
