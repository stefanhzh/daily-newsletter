#!/usr/bin/env python3
"""Hugging Face ingestion adapter."""

from __future__ import annotations

from datetime import datetime

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class HuggingFaceAdapter(BaseAdapter):
    source_id = "huggingface"
    feed_url = "https://huggingface.co/blog/feed.xml"

    def fetch(self) -> list[IngestedItem]:
        try:
            rss_text = self.request_text(self.feed_url)
            rows = parse_rss_items(rss_text)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            item = self._row_to_item(row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _row_to_item(self, row: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(row.get("title", ""))
        link = row.get("link", "").strip()
        raw_pub_date = row.get("pubDate", "").strip()
        summary = self.clean_text(row.get("description", ""))
        if not title or not link or not raw_pub_date:
            return None

        try:
            published_at = self.normalize_published_at(raw_pub_date)
        except Exception:
            return None
        if not self.within_lookback(datetime.fromisoformat(published_at)):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_at,
            summary=summary[:320].strip(),
            byline="Hugging Face",
            section="blog",
            discovery_method="huggingface_blog_feed",
            body_text="",
            fulltext_note="article_page_required_for_fulltext",
        )
