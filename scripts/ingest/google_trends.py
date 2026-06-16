#!/usr/bin/env python3
"""Google Trends ranking/trend ingestion adapter."""

from __future__ import annotations

from urllib.parse import quote
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


class GoogleTrendsAdapter(BaseAdapter):
    source_id = "google-trends"
    rss_url = "https://trends.google.com/trending/rss?geo=US"
    rank_section = "US Daily Search Trends"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.rss_url)
        except Exception:
            return []

        root = ET.fromstring(xml_text)
        items = root.findall("./channel/item")
        collected: list[IngestedItem] = []
        for idx, node in enumerate(items, start=1):
            item = self._node_to_item(node, idx)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _node_to_item(self, node: ET.Element, rank_position: int) -> IngestedItem | None:
        ns = {"ht": "https://trends.google.com/trending/rss"}
        title = self.clean_text(node.findtext("title", default=""))
        if not title:
            return None

        approx_traffic = self.clean_text(node.findtext("ht:approx_traffic", default="", namespaces=ns))
        published_at = self.normalize_published_at(node.findtext("pubDate", default=""))
        canonical_url = (
            "https://trends.google.com/trends/explore"
            f"?q={quote(title)}&date=now%201-d&geo=US&hl=en-US"
        )

        related_titles: list[str] = []
        related_urls: list[str] = []
        for news_item in node.findall("ht:news_item", ns):
            news_title = self.clean_text(news_item.findtext("ht:news_item_title", default="", namespaces=ns))
            news_url = self.clean_text(news_item.findtext("ht:news_item_url", default="", namespaces=ns))
            if news_title:
                related_titles.append(news_title)
            if news_url:
                related_urls.append(news_url)

        summary_parts: list[str] = []
        if approx_traffic:
            summary_parts.append(f"Approx traffic: {approx_traffic}")
        if related_titles:
            summary_parts.append(f"Related news: {related_titles[0]}")
        summary = " | ".join(summary_parts)

        fulltext_note = "ranking_surface_no_native_article_body"
        if related_urls:
            fulltext_note += f" | related_news_url={related_urls[0]}"

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=self.rss_url,
            canonical_url=canonical_url,
            published_at=published_at,
            summary=summary,
            byline="Google Trends",
            section="daily_trends",
            discovery_method="google_trends_rss",
            body_text="",
            fulltext_status="partial_only",
            fulltext_note=fulltext_note,
            rank_position=rank_position,
            rank_section=self.rank_section,
        )
