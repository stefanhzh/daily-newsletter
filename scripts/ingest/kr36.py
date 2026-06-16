#!/usr/bin/env python3
"""36Kr ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class Kr36Adapter(BaseAdapter):
    source_id = "36kr"
    feed_url = "https://36kr.com/feed"

    def fetch(self) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(self.feed_url)
            rows = parse_rss_items(xml_text)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            item = self._row_to_item(row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _row_to_item(self, row: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(row.get("title", ""))
        link = self._normalize_link(row.get("link", ""))
        raw_date = row.get("pubDate", "")
        description_html = row.get("description", "")
        if not title or not link or not raw_date:
            return None

        try:
            published_at = self._normalize_36kr_time(raw_date)
        except Exception:
            return None

        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if not self.within_lookback(published_dt):
            return None

        summary, byline = self._parse_description(description_html)
        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_at,
            summary=summary[:320],
            byline=byline or "36氪",
            section="feed",
            discovery_method="36kr_official_feed",
        )

    def _normalize_link(self, link: str) -> str:
        link = (link or "").strip()
        if "?f=rss" in link:
            link = link.replace("?f=rss", "")
        return link

    def _parse_description(self, html_fragment: str) -> tuple[str, str]:
        if not html_fragment:
            return "", ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        paragraphs = [
            self.clean_text(node.get_text(" ", strip=True))
            for node in soup.find_all("p")
        ]
        paragraphs = [p for p in paragraphs if p]
        byline = ""
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if paragraph.startswith(("作者", "作者｜", "作者丨", "文｜", "编辑", "编辑｜", "编辑丨")):
                if not byline:
                    byline = paragraph
                continue
            cleaned.append(paragraph)
        summary = cleaned[0] if cleaned else ""
        return summary, byline

    def _normalize_36kr_time(self, raw_value: str) -> str:
        raw_value = (raw_value or "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S  %z", "%Y-%m-%d %H:%M:%S %z"):
            try:
                parsed = datetime.strptime(raw_value, fmt)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                continue
        try:
            return self.normalize_published_at(raw_value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(raw_value) from exc
