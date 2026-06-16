#!/usr/bin/env python3
"""Discord Blog ingestion adapter."""

from __future__ import annotations

from datetime import datetime

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class DiscordBlogAdapter(BaseAdapter):
    source_id = "discord-blog"
    feed_url = "https://discord.com/blog/rss.xml"

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
        link = entry.get("link", "").strip()
        raw_pub_date = entry.get("pubDate", "").strip()
        summary = self.clean_text(entry.get("description", ""))
        if not title or not link or not raw_pub_date:
            return None

        if not link.startswith("https://discord.com/blog/"):
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
            byline="Discord",
            section="blog",
            discovery_method="discord_blog_rss",
            fulltext_note="article_page_required_for_fulltext",
        )
