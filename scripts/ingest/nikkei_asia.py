#!/usr/bin/env python3
"""Nikkei Asia ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class NikkeiAsiaAdapter(BaseAdapter):
    source_id = "nikkei-asia"
    feed_url = "https://asia.nikkei.com/rss/feed/nar"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for entry in self._parse_feed(xml_text)[:50]:
            item = self._entry_to_item(entry)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _parse_feed(self, xml_text: str) -> list[dict[str, str]]:
        root = ET.fromstring(xml_text)
        items: list[dict[str, str]] = []
        for node in root.findall(".//{http://purl.org/rss/1.0/}item"):
            items.append(
                {
                    "title": node.findtext("{http://purl.org/rss/1.0/}title", default=""),
                    "link": node.findtext("{http://purl.org/rss/1.0/}link", default=""),
                }
            )
        return items

    def _entry_to_item(self, entry: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        if not title or not link:
            return None

        metadata = self._fetch_article_metadata(link)
        if metadata is None:
            return None

        published_dt = metadata["published_dt"]
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=metadata["headline"] or title,
            source_url=link,
            canonical_url=link,
            published_at=published_dt.isoformat(),
            summary=metadata["summary"],
            byline=metadata["byline"],
            section=metadata["section"],
            discovery_method="nikkei_asia_rss_plus_next_data",
        )

    def _fetch_article_metadata(self, url: str) -> dict[str, object] | None:
        try:
            html = self.request_text(url)
        except Exception:
            return None

        match = NEXT_DATA_RE.search(html)
        if not match:
            return None

        try:
            data = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        published_dt = self._extract_published_dt(data)
        if published_dt is None:
            return None

        headline = self.clean_text(str(data.get("headline", "")))
        summary = self.clean_text(str(data.get("subhead") or data.get("missile") or ""))
        byline = self._extract_byline(data.get("author"))
        section = self._extract_section(data)
        return {
            "headline": headline,
            "summary": summary,
            "byline": byline,
            "section": section,
            "published_dt": published_dt,
        }

    def _extract_published_dt(self, data: dict[str, object]) -> datetime | None:
        for key in ("displayDate", "createdDate", "lastModifiedDate"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            if isinstance(value, str) and value.isdigit():
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
                except ValueError:
                    continue
        return None

    def _extract_byline(self, author_value: object) -> str:
        if isinstance(author_value, dict):
            return self.clean_text(str(author_value.get("name", "")))
        if isinstance(author_value, list):
            names = []
            for item in author_value:
                if isinstance(item, dict):
                    name = self.clean_text(str(item.get("name", "")))
                    if name:
                        names.append(name)
            return ", ".join(names)
        return ""

    def _extract_section(self, data: dict[str, object]) -> str:
        for key in ("primaryTag", "rootCategory", "primaryRegion"):
            value = data.get(key)
            if isinstance(value, dict):
                name = self.clean_text(str(value.get("name", "")))
                if name:
                    return name
        return "latest"
