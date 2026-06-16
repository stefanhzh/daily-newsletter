#!/usr/bin/env python3
"""Stratechery ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import re

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class StratecheryAdapter(BaseAdapter):
    source_id = "stratechery"
    api_url = (
        "https://stratechery.com/wp-json/wp/v2/posts"
        "?per_page=30&_fields=link,date_gmt,title.rendered,excerpt.rendered,content.rendered"
    )

    def fetch(self) -> list[IngestedItem]:
        try:
            payload = self.request_text(self.api_url)
            rows = json.loads(payload)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            item = self._row_to_item(row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _row_to_item(self, row: dict[str, object]) -> IngestedItem | None:
        link = str(row.get("link", "")).strip()
        raw_date = str(row.get("date_gmt", "")).strip()
        title_html = ((row.get("title") or {}) if isinstance(row.get("title"), dict) else {})
        excerpt_html = ((row.get("excerpt") or {}) if isinstance(row.get("excerpt"), dict) else {})
        content_html = ((row.get("content") or {}) if isinstance(row.get("content"), dict) else {})

        title = self._strip_html(str(title_html.get("rendered", "")))
        summary = self._build_summary(str(excerpt_html.get("rendered", "")), str(content_html.get("rendered", "")))
        if not link or not raw_date or not title:
            return None

        try:
            published_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline="Ben Thompson",
            section="latest",
            discovery_method="stratechery_wp_json_api",
            body_text="",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _build_summary(self, excerpt_html: str, content_html: str) -> str:
        candidates = [excerpt_html, content_html]
        for html_fragment in candidates:
            if not html_fragment:
                continue
            soup = BeautifulSoup(html_fragment, "html.parser")
            texts = []
            for node in soup.find_all(["p", "li"]):
                text = self.clean_text(unescape(node.get_text(" ", strip=True)))
                if len(text) >= 20:
                    texts.append(text)
            if texts:
                return texts[0]
            text = re.sub(r"<[^>]+>", " ", html_fragment)
            text = self.clean_text(unescape(text))
            if text:
                return text
        return ""

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        return self.clean_text(unescape(text))
