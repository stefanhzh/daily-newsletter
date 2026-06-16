#!/usr/bin/env python3
"""CNBC ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class CNBCAdapter(BaseAdapter):
    source_id = "cnbc"
    homepage_url = "https://www.cnbc.com/"
    feeds = [
        ("top-news", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("world", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
        ("finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
        ("technology", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
    ]

    def fetch(self) -> list[IngestedItem]:
        feed_items_by_url: dict[str, IngestedItem] = {}
        collected: list[IngestedItem] = []
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in parse_rss_items(xml_text)[:20]:
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
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = self._canonicalize_url(anchor.get("href", "").strip())
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not self._is_article_url(href) or href in seen or len(title) < 25:
                continue
            seen.add(href)
            source_item = feed_items_by_url.get(href)
            published_at = source_item.published_at if source_item else self._published_at_from_url(href)
            if not published_at:
                continue
            section = self._article_section_from_url(href)
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=source_item.title if source_item else title,
                    source_url=href,
                    canonical_url=href,
                    published_at=published_at,
                    summary=source_item.summary if source_item else "",
                    byline="CNBC",
                    section=section,
                    discovery_method="cnbc_homepage_ranked_html",
                    rank_position=len(items) + 1,
                    rank_section="homepage_ranked",
                )
            )
            if len(items) >= 25:
                break
        return items

    def _is_article_url(self, url: str) -> bool:
        return bool(re.match(r"^https://www\.cnbc\.com/20\d{2}/\d{2}/\d{2}/.+\.html$", url))

    def _published_at_from_url(self, url: str) -> str:
        match = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url)
        if not match:
            return ""
        published_dt = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone.utc,
        )
        if not self.within_lookback(published_dt):
            return ""
        return published_dt.isoformat()

    def _article_section_from_url(self, url: str) -> str:
        try:
            html = self.request_text(url, timeout=20)
        except Exception:
            return ""

        match = re.search(r'"articleSection"\s*:\s*"([^"]+)"', html)
        if match:
            return self._broad_section(self.clean_text(match.group(1)))

        soup = BeautifulSoup(html, "html.parser")
        for selector in [
            'meta[property="article:section"]',
            'meta[name="article:section"]',
            'meta[name="parsely-section"]',
        ]:
            node = soup.select_one(selector)
            if node and node.get("content"):
                return self._broad_section(self.clean_text(node.get("content", "")))
        return ""

    def _broad_section(self, section: str) -> str:
        normalized = section.strip().lower()
        if not normalized:
            return ""
        if "market" in normalized:
            return "Markets"
        if "investing" in normalized or normalized in {"pro home", "cnbc pro"}:
            return "Investing"
        if "economy" in normalized:
            return "Economy"
        if "business" in normalized:
            return "Business"
        if "tech" in normalized:
            return "Technology"
        if "politic" in normalized:
            return "Politics"
        if "world" in normalized:
            return "World"
        return section

    def _canonicalize_url(self, url: str) -> str:
        if url.startswith("/"):
            url = "https://www.cnbc.com" + url
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        published = entry.get("pubDate", "").strip()
        if not title or not link or not published:
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
            byline="CNBC",
            section=section_name,
            discovery_method="cnbc_official_rss",
        )

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(unescape(text))
