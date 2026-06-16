#!/usr/bin/env python3
"""ZeroHedge ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class ZeroHedgeAdapter(BaseAdapter):
    source_id = "zerohedge"
    homepage_url = "https://www.zerohedge.com/"
    feed_url = "https://cms.zerohedge.com/fullrss2.xml"

    def fetch(self) -> list[IngestedItem]:
        feed_items_by_url: dict[str, IngestedItem] = {}
        try:
            xml_text = self.request_text(self.feed_url)
        except Exception:
            xml_text = ""

        collected: list[IngestedItem] = []
        if xml_text:
            for entry in parse_rss_items(xml_text)[:60]:
                item = self._entry_to_item(entry)
                if item is not None:
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
            if not source_item:
                continue
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=source_item.title,
                    source_url=href,
                    canonical_url=href,
                    published_at=source_item.published_at,
                    summary=source_item.summary,
                    byline="ZeroHedge",
                    section="homepage_ranked",
                    discovery_method="zerohedge_homepage_ranked_html",
                    fulltext_note="article_page_required_for_fulltext",
                    rank_position=len(items) + 1,
                    rank_section="homepage_ranked",
                )
            )
            if len(items) >= 25:
                break
        return items

    def _is_article_url(self, url: str) -> bool:
        return bool(re.match(r"^https://www\.zerohedge\.com/(markets|geopolitical|political|technology|economics|energy)/", url))

    def _canonicalize_url(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))

    def _entry_to_item(self, entry: dict[str, str]) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = entry.get("link", "").strip()
        raw_pub_date = entry.get("pubDate", "").strip()
        summary = self._extract_description(entry.get("description", ""))
        if not title or not link or not raw_pub_date:
            return None

        link = self._canonicalize_url(link)
        if not re.match(r"^https://www\.zerohedge\.com/", link):
            return None

        try:
            published_at = self.normalize_published_at(raw_pub_date)
        except Exception:
            return None
        if not self.within_lookback(datetime.fromisoformat(published_at)):
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=link,
            canonical_url=link,
            published_at=published_at,
            summary=summary[:320].strip(),
            byline="ZeroHedge",
            section="news",
            discovery_method="zerohedge_rss",
            fulltext_note="article_page_required_for_fulltext",
        )

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        return self.clean_text(text)
