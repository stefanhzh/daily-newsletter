#!/usr/bin/env python3
"""Axios ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class AxiosAdapter(BaseAdapter):
    source_id = "axios"
    feed_url = "https://api.axios.com/feed/"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for position, entry in enumerate(self._parse_feed(xml_text)[:100], start=1):
            item = self._entry_to_item(entry, position)
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

    def _entry_to_item(self, entry: dict[str, str], rank_position: int) -> IngestedItem | None:
        title = self._normalize_text(self.clean_text(entry.get("title", "")))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
            return None

        published_iso = self.normalize_published_at(published)
        published_dt = datetime.fromisoformat(published_iso)
        if not self.within_lookback(published_dt):
            return None

        body_text = self._extract_body(entry.get("content", ""))
        summary = self._extract_summary(entry.get("description", ""), body_text)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_iso,
            summary=summary,
            byline=self._normalize_text(self.clean_text(entry.get("creator", ""))),
            section="",
            discovery_method="axios_official_rss_homepage_rank_proxy",
            body_text=body_text,
            fulltext_note="rss_content_encoded",
            rank_position=rank_position,
            rank_section="homepage_rank_proxy",
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
            return self._normalize_text(self.clean_text(unescape(text)))
        return "\n\n".join(paragraphs)

    def _extract_summary(self, description_html: str, body_text: str) -> str:
        if description_html:
            text = re.sub(r"<[^>]+>", " ", description_html)
            text = self._normalize_text(self.clean_text(unescape(text)))
            if text:
                return text[:320].strip()
        if body_text:
            return body_text.split("\n\n", 1)[0][:320].strip()
        return ""

    def _normalize_text(self, value: str) -> str:
        replacements = {
            "бк": " -- ",
            "’": "'",
            "‘": "'",
            "“": "\"",
            "”": "\"",
            "—": "--",
            "–": "-",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        value = re.sub(r"\s+", " ", value).strip()
        return value
