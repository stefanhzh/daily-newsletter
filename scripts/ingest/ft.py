#!/usr/bin/env python3
"""Financial Times ingestion adapter."""

from __future__ import annotations

from datetime import datetime

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class FTAdapter(BaseAdapter):
    source_id = "ft"
    home_feed = ("home", "https://www.ft.com/rss/home")
    feeds = [
        ("world", "https://www.ft.com/rss/world"),
        ("markets", "https://www.ft.com/rss/markets"),
        ("technology", "https://www.ft.com/rss/technology"),
        ("companies", "https://www.ft.com/rss/companies"),
    ]

    def fetch(self) -> list[IngestedItem]:
        section_by_url: dict[str, str] = {}
        collected: list[IngestedItem] = []

        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in parse_rss_items(xml_text)[:30]:
                item = self._entry_to_item(entry, section_name)
                if item:
                    section_by_url.setdefault(item.canonical_url, item.section)

        try:
            home_xml = self.request_text(self.home_feed[1])
        except Exception:
            home_xml = ""
        if home_xml:
            for rank, entry in enumerate(parse_rss_items(home_xml)[:30], start=1):
                item = self._entry_to_item(entry, self.home_feed[0])
                if not item:
                    continue
                item.section = section_by_url.get(item.canonical_url, "")
                item.rank_position = rank
                item.rank_section = "home_rss_ranked"
                collected.append(item)

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

        if "/content/" not in link:
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
            summary=self.clean_text(entry.get("description", "")),
            byline="Financial Times",
            section="" if section_name == "home" else section_name,
            discovery_method="ft_official_rss",
        )
