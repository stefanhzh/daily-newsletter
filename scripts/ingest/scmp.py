#!/usr/bin/env python3
"""South China Morning Post ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


TAG_RE = re.compile(r"<[^>]+>")


class SCMPAdapter(BaseAdapter):
    source_id = "scmp"
    feeds = [
        ("news", "https://www.scmp.com/rss/91/feed"),
        ("china", "https://www.scmp.com/rss/4/feed"),
    ]

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in self._parse_feed(xml_text)[:50]:
                item = self._entry_to_item(entry, section_name)
                if item is not None:
                    collected.append(item)
        return dedupe_items(collected)

    def _parse_feed(self, xml_text: str) -> list[dict[str, str]]:
        root = ET.fromstring(xml_text)
        items: list[dict[str, str]] = []
        for node in root.findall("./channel/item"):
            items.append(
                {
                    "title": node.findtext("title", default=""),
                    "link": node.findtext("link", default=""),
                    "pubDate": node.findtext("pubDate", default=""),
                    "description": node.findtext("description", default=""),
                }
            )
        return items

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = self._canonicalize_link(entry.get("link", "").strip())
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
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
            summary=self._strip_html(entry.get("description", "")),
            byline="South China Morning Post",
            section=section_name,
            discovery_method="scmp_official_rss",
        )

    def _strip_html(self, value: str) -> str:
        text = TAG_RE.sub(" ", value or "")
        return self.clean_text(unescape(text))

    def _canonicalize_link(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
