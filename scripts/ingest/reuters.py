#!/usr/bin/env python3
"""Reuters ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items, title_key


class ReutersAdapter(BaseAdapter):
    source_id = "reuters"
    sitemap_index_url = "https://www.reuters.com/arc/outboundfeeds/news-sitemap-index/?outputType=xml"
    google_queries = [
        "site:reuters.com when:1d",
        "site:reuters.com world when:1d",
        "site:reuters.com business when:1d",
        "site:reuters.com markets when:1d",
        "site:reuters.com technology when:1d",
        "site:reuters.com china when:1d",
    ]
    allowed_path_markers = (
        "/world/",
        "/business/",
        "/markets/",
        "/technology/",
    )

    def fetch(self) -> list[IngestedItem]:
        summary_by_title = self._fetch_google_summaries()
        sitemap_urls = self._fetch_sitemap_urls()
        collected: list[IngestedItem] = []

        for sitemap_url in sitemap_urls:
            try:
                xml_text = self.request_text(sitemap_url)
            except Exception:
                continue

            page_items = self._parse_sitemap_page(xml_text, summary_by_title)
            if not page_items:
                break
            collected.extend(page_items)

        return dedupe_items(collected)

    def _fetch_google_summaries(self) -> dict[str, str]:
        summary_map: dict[str, str] = {}
        for query in self.google_queries:
            feed_url = "https://news.google.com/rss/search?q=" + quote(query)
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue

            for entry in parse_rss_items(xml_text)[:15]:
                raw_title = self.clean_text(entry.get("title", ""))
                if " - Reuters" not in raw_title:
                    continue
                clean_title = raw_title.replace(" - Reuters", "").strip()
                summary = self._extract_description(entry.get("description", ""))
                if not summary:
                    continue
                summary_map.setdefault(title_key(clean_title), summary)
        return summary_map

    def _fetch_sitemap_urls(self) -> list[str]:
        xml_text = self.request_text(self.sitemap_index_url)
        root = ET.fromstring(xml_text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        return [node.text or "" for node in root.findall(".//sm:loc", ns)]

    def _parse_sitemap_page(
        self,
        xml_text: str,
        summary_by_title: dict[str, str],
    ) -> list[IngestedItem]:
        root = ET.fromstring(xml_text)
        ns = {
            "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
            "news": "http://www.google.com/schemas/sitemap-news/0.9",
        }
        items: list[IngestedItem] = []

        for node in root.findall(".//sm:url", ns):
            loc = node.findtext("sm:loc", default="", namespaces=ns)
            title = node.findtext(".//news:title", default="", namespaces=ns)
            published = node.findtext(".//news:publication_date", default="", namespaces=ns)
            if not loc or not title or not published:
                continue
            if not any(marker in loc for marker in self.allowed_path_markers):
                continue

            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if not self.within_lookback(published_dt):
                continue

            clean_title = self.clean_text(title)
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=clean_title,
                    source_url=loc,
                    canonical_url=loc,
                    published_at=published_dt.isoformat(),
                    summary=summary_by_title.get(title_key(clean_title), ""),
                    byline="Reuters",
                    section=self._classify_section(loc),
                    discovery_method="reuters_news_sitemap",
                )
            )

        return items

    def _classify_section(self, url: str) -> str:
        for marker in self.allowed_path_markers:
            if marker in url:
                return marker.strip("/")
        return "news"

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        text = self.clean_text(unescape(text))
        text = re.sub(r"\s+Reuters$", "", text).strip()
        return text
