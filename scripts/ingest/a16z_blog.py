#!/usr/bin/env python3
"""a16z Blog ingestion adapter."""

from __future__ import annotations

from datetime import datetime
import re

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, extract_meta_content


class A16ZBlogAdapter(BaseAdapter):
    source_id = "a16z-blog"
    listing_url = "https://a16z.com/news-content/"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.listing_url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items: list[IngestedItem] = []
        for card in soup.select("div[data-feed-item]")[:80]:
            item = self._card_to_item(card)
            if item is not None:
                items.append(item)
        return dedupe_items(items)

    def _card_to_item(self, card: BeautifulSoup) -> IngestedItem | None:
        link_node = card.select_one("h4 a[href]")
        section_node = card.select_one("span[class*='post-eyebrow']")
        byline_node = card.select_one("div.flex span")
        if link_node is None:
            return None

        title = self.clean_text(link_node.get_text(" ", strip=True))
        link = (link_node.get("href") or "").strip()
        if not title or not link.startswith("https://a16z.com/"):
            return None
        if "/announcement/" in link:
            section = "announcement"
        else:
            section = self.clean_text(section_node.get_text(" ", strip=True)).lower() if section_node else "blog"
        byline = self.clean_text(byline_node.get_text(" ", strip=True)) if byline_node else "a16z"

        published_at, summary = self._fetch_metadata(link)
        if not published_at:
            return None
        try:
            published_dt = datetime.fromisoformat(published_at)
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_at,
            summary=summary,
            byline=byline,
            section=section or "blog",
            discovery_method="a16z_news_content_listing",
            body_text="",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _fetch_metadata(self, url: str) -> tuple[str, str]:
        try:
            html = self.request_text(url)
        except Exception:
            return "", ""

        published = ""
        match = re.search(r'"datePublished":"([^"]+)"', html)
        if match:
            published = match.group(1)
        else:
            published = extract_meta_content(html, "article:published_time")

        summary = extract_meta_content(html, "og:description") or extract_meta_content(html, "description")
        return published, self.clean_text(summary)[:320].strip()
