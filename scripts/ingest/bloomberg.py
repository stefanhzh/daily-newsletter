#!/usr/bin/env python3
"""Bloomberg ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class BloombergAdapter(BaseAdapter):
    source_id = "bloomberg"
    feeds = [
        ("markets", "https://www.bloomberg.com/feeds/markets/news.rss"),
        ("politics", "https://www.bloomberg.com/feeds/politics/news.rss"),
        ("technology", "https://www.bloomberg.com/feeds/technology/news.rss"),
        ("economics", "https://www.bloomberg.com/feeds/economics/news.rss"),
        ("industries", "https://www.bloomberg.com/feeds/industries/news.rss"),
        ("wealth", "https://www.bloomberg.com/feeds/wealth/news.rss"),
        ("green", "https://www.bloomberg.com/feeds/green/news.rss"),
        ("crypto", "https://www.bloomberg.com/feeds/crypto/news.rss"),
    ]

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in parse_rss_items(xml_text)[:30]:
                item = self._entry_to_item(entry, section_name)
                if item:
                    collected.append(item)
        return dedupe_items(collected)

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
            return None

        # Bloomberg feeds mix in video/audio episodes; keep the written article stream clean by default.
        if "/news/articles/" not in link:
            return None

        published_iso = self.normalize_published_at(published)
        published_dt = datetime.fromisoformat(published_iso)
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_iso,
            summary=self._extract_description(entry.get("description", "")),
            byline="Bloomberg",
            section=section_name,
            discovery_method="bloomberg_official_rss",
        )

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(unescape(text))
