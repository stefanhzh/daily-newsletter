#!/usr/bin/env python3
"""LessWrong ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import re

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class LessWrongAdapter(BaseAdapter):
    source_id = "lesswrong"
    feed_url = "https://www.lesswrong.com/feed.xml"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for entry in parse_rss_items(xml_text)[:60]:
            item = self._entry_to_item(entry)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _entry_to_item(self, entry: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        raw_pub_date = entry.get("pubDate", "").strip()
        description_html = entry.get("description", "") or ""
        if not title or not link or not raw_pub_date:
            return None

        if not link.startswith("https://www.lesswrong.com/posts/"):
            return None
        if "commentId=" in link:
            return None

        try:
            published_at = self.normalize_published_at(raw_pub_date)
        except Exception:
            return None
        if not self.within_lookback(datetime.fromisoformat(published_at)):
            return None

        summary = self._extract_summary(description_html)
        body_text = self._html_to_plaintext(description_html)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_at,
            summary=summary[:320].strip(),
            byline="LessWrong",
            section="posts",
            discovery_method="lesswrong_feed",
            body_text=body_text,
            fulltext_note="rss_description_html",
        )

    def _extract_summary(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(text)

    def _html_to_plaintext(self, html_snippet: str) -> str:
        chunks = re.findall(r"<p[^>]*>(.*?)</p>", html_snippet, re.S | re.I)
        paragraphs: list[str] = []
        for chunk in chunks:
            plain = re.sub(r"<[^>]+>", " ", chunk)
            plain = self.clean_text(plain)
            if len(plain) >= 20 and plain not in paragraphs:
                paragraphs.append(plain)
        return "\n\n".join(paragraphs)
