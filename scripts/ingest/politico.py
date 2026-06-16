#!/usr/bin/env python3
"""Politico ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class PoliticoAdapter(BaseAdapter):
    source_id = "politico"
    feeds = [
        ("politics", "https://rss.politico.com/politics-news.xml"),
        ("whitehouse", "https://rss.politico.com/whitehouse.xml"),
    ]

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in self._parse_feed(xml_text)[:40]:
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
                    "creator": node.findtext("{http://purl.org/dc/elements/1.1/}creator", default=""),
                    "content": node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", default=""),
                }
            )
        return items

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
            return None

        published_iso = self.normalize_published_at(published)
        published_dt = datetime.fromisoformat(published_iso)
        if not self.within_lookback(published_dt):
            return None

        body_text = self._extract_body(entry.get("content", ""))
        summary = self.clean_text(entry.get("description", "")) or self._summary_from_body(body_text)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_iso,
            summary=summary,
            byline=self.clean_text(entry.get("creator", "")),
            section=section_name,
            discovery_method="politico_official_rss",
            body_text=body_text,
            fulltext_note="rss_content_encoded",
        )

    def _extract_body(self, html_fragment: str) -> str:
        if not html_fragment:
            return ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        for node in soup.select("script, style, img, figure, iframe, aside"):
            node.decompose()
        paragraphs = []
        for node in soup.find_all(["p", "li"]):
            text = self._normalize_text(self.clean_text(unescape(node.get_text(" ", strip=True))))
            if len(text) >= 20:
                paragraphs.append(text)
        if not paragraphs:
            text = re.sub(r"<[^>]+>", " ", html_fragment)
            text = self._normalize_text(self.clean_text(unescape(text)))
            return text
        return "\n\n".join(paragraphs)

    def _summary_from_body(self, body_text: str) -> str:
        if not body_text:
            return ""
        first = body_text.split("\n\n", 1)[0]
        return first[:260].strip()

    def _normalize_text(self, value: str) -> str:
        replacements = {
            "〞": "—",
            "＊": "'",
            "※": "\"",
            "§": "\"",
            "毎": "—",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
