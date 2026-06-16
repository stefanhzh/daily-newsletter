#!/usr/bin/env python3
"""TradingView News ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class TradingViewNewsAdapter(BaseAdapter):
    source_id = "tradingview-news"
    news_url = "https://www.tradingview.com/news/"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.news_url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for node in soup.find_all("a", href=True):
            href = node.get("href", "").strip()
            if not href.startswith("/news/tradingview:"):
                continue
            full_url = urljoin("https://www.tradingview.com", href)
            if full_url not in links:
                links.append(full_url)

        collected: list[IngestedItem] = []
        for url in links[:30]:
            item = self._fetch_article_item(url)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _fetch_article_item(self, url: str) -> IngestedItem | None:
        try:
            html = self.request_text(url)
        except Exception:
            return None
        story = self._extract_story(html)
        if not story:
            return None

        title = self.clean_text(str(story.get("title", "")))
        published_ts = story.get("published")
        summary = self.clean_text(str(story.get("short_description", "")))
        if not title or not published_ts:
            return None

        try:
            published_dt = datetime.fromtimestamp(int(published_ts), tz=timezone.utc)
        except Exception:
            return None
        if not self.within_lookback(published_dt):
            return None

        provider = story.get("provider", {}) if isinstance(story.get("provider"), dict) else {}
        byline = self.clean_text(str(provider.get("name", "TradingView"))) or "TradingView"
        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=url,
            canonical_url=url,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline=byline,
            section="news",
            discovery_method="tradingview_news_listing",
            fulltext_note="article_page_embedded_story_payload",
        )

    def _extract_story(self, html: str) -> dict[str, object]:
        soup = BeautifulSoup(html, "html.parser")
        for node in soup.find_all("script", attrs={"type": "application/prs.init-data+json"}):
            raw = node.string or node.get_text() or ""
            if '"story"' not in raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for value in payload.values():
                if not isinstance(value, dict):
                    continue
                story = value.get("story")
                if isinstance(story, dict):
                    return story
        return {}
