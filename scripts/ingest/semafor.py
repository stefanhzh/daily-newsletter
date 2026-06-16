#!/usr/bin/env python3
"""Semafor ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class SemaforAdapter(BaseAdapter):
    source_id = "semafor"
    homepage_url = "https://www.semafor.com/"
    feeds = [
        ("home", "https://www.semafor.com/rss.xml"),
    ]

    def fetch(self) -> list[IngestedItem]:
        feed_items_by_url: dict[str, IngestedItem] = {}
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in parse_rss_items(xml_text)[:40]:
                item = self._entry_to_item(entry, section_name)
                if item:
                    feed_items_by_url.setdefault(self._canonicalize_url(item.canonical_url), item)
        collected.extend(self._fetch_homepage_ranked(feed_items_by_url))
        collected.extend(feed_items_by_url.values())
        return dedupe_items(collected)

    def _fetch_homepage_ranked(self, feed_items_by_url: dict[str, IngestedItem]) -> list[IngestedItem]:
        try:
            html = self.request_text(self.homepage_url, timeout=30)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items: list[IngestedItem] = []
        seen_urls: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = self._canonicalize_url(urljoin(self.homepage_url, anchor.get("href", "").strip()))
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not self._is_article_url(href) or href in seen_urls or len(title) < 20:
                continue
            seen_urls.add(href)
            source_item = feed_items_by_url.get(href)
            published_at = source_item.published_at if source_item else self._published_at_from_url(href)
            if not published_at:
                continue
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=source_item.title if source_item else title,
                    source_url=href,
                    canonical_url=href,
                    published_at=published_at,
                    summary=source_item.summary if source_item else "",
                    byline="Semafor",
                    section="homepage_ranked",
                    discovery_method="semafor_homepage_ranked_html",
                    rank_position=len(items) + 1,
                    rank_section="homepage_ranked",
                )
            )
            if len(items) >= 25:
                break
        return items

    def _is_article_url(self, url: str) -> bool:
        return bool(re.match(r"^https://www\.semafor\.com/article/", url))

    def _published_at_from_url(self, url: str) -> str:
        match = re.search(r"/article/(\d{2})/(\d{2})/(20\d{2})/", url)
        if not match:
            return ""
        published_dt = datetime(
            int(match.group(3)),
            int(match.group(1)),
            int(match.group(2)),
            tzinfo=timezone.utc,
        )
        if not self.within_lookback(published_dt):
            return ""
        return published_dt.isoformat()

    def _canonicalize_url(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
            return None

        # Keep the written article stream clean; skip newsletters, podcasts, and topic pages.
        link = self._canonicalize_url(link)
        if "/article/" not in link:
            return None

        published_iso = self.normalize_published_at(published)
        published_dt = datetime.fromisoformat(published_iso)
        if not self.within_lookback(published_dt):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_iso,
            summary=self._extract_description(entry.get("description", "")),
            byline="Semafor",
            section=section_name,
            discovery_method="semafor_official_rss",
        )

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(unescape(text))
