#!/usr/bin/env python3
"""Lenny's Newsletter ingestion adapter."""

from __future__ import annotations

from datetime import datetime
from html import unescape
import json

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class LennysNewsletterAdapter(BaseAdapter):
    source_id = "lennys-newsletter"
    api_url = "https://www.lennysnewsletter.com/api/v1/posts?limit=30"

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
        audience = row.get("audience")
        title = self.clean_text(str(row.get("title", "")))
        link = str(row.get("canonical_url", "")).strip()
        raw_date = str(row.get("post_date", "")).strip()
        subtitle = self.clean_text(str(row.get("subtitle", "")))
        body_html = row.get("body_html")
        if not title or not link or not raw_date:
            return None

        try:
            published_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        body_text = self._html_to_body(body_html if isinstance(body_html, str) else "")
        summary = subtitle or self._first_paragraph(body_text)
        note = "body_from_substack_api" if audience == "everyone" and body_text else "paywalled_or_preview_only"

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline="Lenny's Newsletter",
            section="newsletter",
            discovery_method="lennys_substack_api",
            body_text=body_text,
            fulltext_note=note,
        )

    def _html_to_body(self, html_fragment: str) -> str:
        if not html_fragment:
            return ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        for node in soup.select("script, style, img, figure, iframe, aside"):
            node.decompose()
        paragraphs: list[str] = []
        for node in soup.find_all(["p", "li"]):
            text = self.clean_text(unescape(node.get_text(" ", strip=True)))
            if len(text) >= 20:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    def _first_paragraph(self, body_text: str) -> str:
        if not body_text:
            return ""
        return body_text.split("\n\n", 1)[0]
