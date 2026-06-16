#!/usr/bin/env python3
"""Wall Street Journal ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


class WSJAdapter(BaseAdapter):
    source_id = "wsj"
    feeds = [
        ("world", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
        ("us", "https://feeds.content.dowjones.io/public/rss/RSSUSNews"),
        ("markets", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
        ("technology", "https://feeds.content.dowjones.io/public/rss/RSSWSJD"),
    ]

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            collected.extend(self._parse_feed(xml_text, section_name))
        return dedupe_items(collected)

    def _parse_feed(self, xml_text: str, section_name: str) -> list[IngestedItem]:
        root = ET.fromstring(xml_text)
        ns = {
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        items: list[IngestedItem] = []

        for node in root.findall("./channel/item"):
            title = self.clean_text(node.findtext("title", default=""))
            link = node.findtext("link", default="").strip()
            published = node.findtext("pubDate", default="").strip()
            if not title or not link or not published:
                continue

            if any(marker in link for marker in ("/livecoverage/", "/video/", "/podcast/")):
                continue

            published_iso = self.normalize_published_at(published)
            published_dt = datetime.fromisoformat(published_iso)
            if not self.within_lookback(published_dt):
                continue

            creator = self.clean_text(node.findtext("dc:creator", default="", namespaces=ns))
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=link,
                    canonical_url=self._canonicalize_url(link),
                    published_at=published_iso,
                    summary=self._extract_description(node.findtext("description", default="")),
                    byline=creator or "Wall Street Journal",
                    section=section_name,
                    discovery_method="wsj_official_rss",
                )
            )

        return items

    def _canonicalize_url(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(unescape(text))
