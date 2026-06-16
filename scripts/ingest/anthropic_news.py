#!/usr/bin/env python3
"""Anthropic News ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, extract_meta_content


class AnthropicNewsAdapter(BaseAdapter):
    source_id = "anthropic-news"
    news_url = "https://www.anthropic.com/news"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.news_url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items: list[IngestedItem] = []
        for link_node in soup.select("ul li a[href^='/news/']")[:80]:
            item = self._link_to_item(link_node)
            if item is not None:
                items.append(item)
        return dedupe_items(items)

    def _link_to_item(self, link_node: BeautifulSoup) -> IngestedItem | None:
        href = (link_node.get("href") or "").strip()
        title_node = link_node.select_one("span[class*='title']")
        time_node = link_node.select_one("time")
        category_node = link_node.select_one("span[class*='subject']")

        title = self.clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        raw_date = self.clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
        section = self.clean_text(category_node.get_text(" ", strip=True)).lower() if category_node else "news"
        if not href or not title or not raw_date:
            return None

        try:
            published_dt = datetime.strptime(raw_date, "%b %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                published_dt = datetime.strptime(raw_date, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        if not self.within_lookback(published_dt):
            return None

        canonical_url = urljoin("https://www.anthropic.com", href)
        summary = self._fetch_summary(canonical_url)
        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=canonical_url,
            canonical_url=canonical_url,
            published_at=published_dt.isoformat(),
            summary=summary,
            byline="Anthropic",
            section=section or "news",
            discovery_method="anthropic_news_listing",
            body_text="",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _fetch_summary(self, url: str) -> str:
        try:
            html = self.request_text(url)
        except Exception:
            return ""
        summary = extract_meta_content(html, "og:description") or extract_meta_content(html, "description")
        return self.clean_text(summary)[:320].strip()
