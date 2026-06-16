#!/usr/bin/env python3
"""Y Combinator blog ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class YCombinatorAdapter(BaseAdapter):
    source_id = "y-combinator"
    feed_url = "https://www.ycombinator.com/blog/rss"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for entry in self._parse_feed(xml_text)[:80]:
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
                    "pubDate": node.findtext("pubDate", default=""),
                    "description": node.findtext("description", default=""),
                    "creator": node.findtext("{http://purl.org/dc/elements/1.1/}creator", default=""),
                    "category": node.findtext("category", default=""),
                    "content": node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", default=""),
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

        body_text = self._extract_body(entry.get("content", ""))
        summary = self.clean_text(entry.get("description", "")) or self._summary_from_body(body_text)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=canonical_url,
            published_at=published_iso,
            summary=summary[:320].strip(),
            byline=self.clean_text(entry.get("creator", "")) or "Y Combinator",
            section=self._section_name(entry.get("category", "")),
            discovery_method="yc_blog_rss",
            body_text=body_text,
            fulltext_note="rss_content_encoded",
        )

    def _normalize_canonical_url(self, link: str) -> str:
        parsed = urlparse(link)
        host = parsed.netloc.lower()
        if host not in {"www.ycombinator.com", "blog.ycombinator.com"}:
            return ""
        path = parsed.path or ""
        if not path.startswith("/blog/"):
            return ""
        if not path.endswith("/"):
            path = f"{path}/"
        return urlunparse(("https", "www.ycombinator.com", path, "", "", ""))

    def _extract_body(self, html_fragment: str) -> str:
        if not html_fragment:
            return ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        for node in soup.select("script, style, img, figure, iframe, aside"):
            node.decompose()
        paragraphs: list[str] = []
        for node in soup.find_all(["p", "li"]):
            text = self._normalize_text(self.clean_text(unescape(node.get_text(" ", strip=True))))
            if len(text) >= 20:
                paragraphs.append(text)
        if not paragraphs:
            text = re.sub(r"<[^>]+>", " ", html_fragment)
            return self._normalize_text(self.clean_text(unescape(text)))
        return "\n\n".join(paragraphs)

    def _summary_from_body(self, body_text: str) -> str:
        if not body_text:
            return ""
        return body_text.split("\n\n", 1)[0][:260].strip()

    def _section_name(self, category: str) -> str:
        normalized = self.clean_text(category).lower()
        return normalized.replace(" ", "-") if normalized else "blog"

    def _normalize_text(self, value: str) -> str:
        replacements = {
            "—": " -- ",
            "\xa0": " ",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return re.sub(r"\s+", " ", value).strip()
