#!/usr/bin/env python3
"""OpenAI News ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


class OpenAIBlogAdapter(BaseAdapter):
    source_id = "openai-blog"
    feed_url = "https://openai.com/news/rss.xml"
    locale_prefix_re = re.compile(r"^/[A-Za-z]{2}(?:-[A-Za-z0-9]+)*/(?=index/)")

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for entry in self._parse_feed(xml_text)[:100]:
            item = self._entry_to_item(entry)
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
                    "guid": node.findtext("guid", default=""),
                    "pubDate": node.findtext("pubDate", default=""),
                    "description": node.findtext("description", default=""),
                    "category": node.findtext("category", default=""),
                }
            )
        return items

    def _entry_to_item(self, entry: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
            return None

        canonical_url = self._normalize_canonical_url(link)
        if not canonical_url:
            return None

        published_iso = self.normalize_published_at(published)
        published_dt = datetime.fromisoformat(published_iso)
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=canonical_url,
            published_at=published_iso,
            summary=self.clean_text(entry.get("description", "")),
            byline="OpenAI",
            section=self._section_name(entry.get("category", ""), canonical_url),
            discovery_method="openai_news_rss",
        )

    def _normalize_canonical_url(self, link: str) -> str:
        parsed = urlparse(link)
        if parsed.netloc != "openai.com":
            return ""

        # The RSS feed mixes newsroom posts with Academy and other surfaces.
        # For the blog/news source we keep only canonical newsroom-style `/index/` items.
        path = parsed.path or ""
        path = self.locale_prefix_re.sub("/" , path)
        if not path.startswith("/index/"):
            return ""
        if not path.endswith("/"):
            path = f"{path}/"

        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    def _section_name(self, category: str, canonical_url: str) -> str:
        normalized_category = self.clean_text(category).lower()
        if normalized_category:
            return normalized_category.replace(" ", "-")

        path = urlparse(canonical_url).path
        if path.startswith("/index/"):
            return "news"
        return "latest"
