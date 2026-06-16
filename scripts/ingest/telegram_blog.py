#!/usr/bin/env python3
"""Telegram Blog ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, extract_meta_content


class TelegramBlogAdapter(BaseAdapter):
    source_id = "telegram-blog"
    blog_url = "https://telegram.org/blog"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.blog_url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items: list[IngestedItem] = []
        seen: set[str] = set()
        for node in soup.find_all("a", href=True):
            href = (node.get("href") or "").strip()
            if not href.startswith("/blog/"):
                continue
            if href == "/blog/":
                continue
            canonical_url = urljoin("https://telegram.org", href)
            if canonical_url in seen:
                continue
            seen.add(canonical_url)
            item = self._fetch_article_item(canonical_url)
            if item is not None:
                items.append(item)
        return dedupe_items(items)

    def _fetch_article_item(self, url: str) -> IngestedItem | None:
        try:
            html = self.request_text(url)
        except Exception:
            return None

        title = self.clean_text(extract_meta_content(html, "og:title"))
        raw_published = extract_meta_content(html, "article:published_time")
        if not title or not raw_published:
            return None

        try:
            published_dt = datetime.fromisoformat(raw_published.replace("Z", "+00:00"))
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        summary = self._extract_summary(url, html)
        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=url,
            canonical_url=url,
            published_at=published_dt.isoformat(),
            summary=summary[:320].strip(),
            byline="Telegram",
            section="blog",
            discovery_method="telegram_blog_listing",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _extract_summary(self, url: str, html: str) -> str:
        summary = extract_meta_content(html, "description")
        if summary:
            return self.clean_text(summary)
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = []
        for node in soup.find_all("p"):
            text = self.clean_text(node.get_text(" ", strip=True))
            if len(text) >= 40:
                paragraphs.append(text)
        if paragraphs:
            return paragraphs[0]
        title_slug = url.rsplit("/", 1)[-1]
        return self.clean_text(title_slug.replace("-", " "))
