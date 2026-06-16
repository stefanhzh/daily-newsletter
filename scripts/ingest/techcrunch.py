#!/usr/bin/env python3
"""TechCrunch ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


TAG_RE = re.compile(r"<[^>]+>")


class TechCrunchAdapter(BaseAdapter):
    source_id = "techcrunch"
    homepage_url = "https://techcrunch.com/"
    api_url = (
        "https://techcrunch.com/wp-json/wp/v2/posts"
        "?per_page=30&_fields=link,date_gmt,title.rendered,excerpt.rendered"
    )

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        collected.extend(self._fetch_homepage_ranked())
        try:
            payload = self.request_text(self.api_url)
            rows = json.loads(payload)
        except Exception:
            rows = []

        for row in rows:
            item = self._row_to_item(row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _fetch_homepage_ranked(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.homepage_url, timeout=30)
        except Exception:
            return []

        collected: list[IngestedItem] = []
        collected.extend(self._extract_homepage_section(html, "Top Headlines", "top_headlines", limit=8))
        collected.extend(self._extract_homepage_section(html, "Most Popular", "most_popular", limit=12))
        return collected

    def _extract_homepage_section(self, html: str, marker: str, section_name: str, *, limit: int) -> list[IngestedItem]:
        marker_pos = html.lower().find(marker.lower())
        if marker_pos < 0:
            return []
        chunk = html[marker_pos : marker_pos + 24_000]
        soup = BeautifulSoup(chunk, "html.parser")
        now_iso = datetime.now(timezone.utc).isoformat()
        items: list[IngestedItem] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            title = self._strip_html(anchor.get_text(" ", strip=True))
            if not self._is_article_url(href) or not title or href in seen:
                continue
            seen.add(href)
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=href,
                    canonical_url=href,
                    published_at=now_iso,
                    summary="",
                    byline="TechCrunch",
                    section=section_name,
                    discovery_method="techcrunch_homepage_ranked_html",
                    rank_position=len(items) + 1,
                    rank_section=section_name,
                )
            )
            if len(items) >= limit:
                break
        return items

    def _is_article_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc != "techcrunch.com":
            return False
        return bool(re.search(r"^/20\d{2}/\d{2}/\d{2}/[^/]+/?$", parsed.path))

    def _row_to_item(self, row: dict[str, object]) -> IngestedItem | None:
        link = str(row.get("link", "")).strip()
        raw_date = str(row.get("date_gmt", "")).strip()
        title_html = ((row.get("title") or {}) if isinstance(row.get("title"), dict) else {})
        excerpt_html = ((row.get("excerpt") or {}) if isinstance(row.get("excerpt"), dict) else {})

        title = self._strip_html(str(title_html.get("rendered", "")))
        summary = self._strip_html(str(excerpt_html.get("rendered", "")))
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
            summary=summary,
            byline="TechCrunch",
            section="latest",
            discovery_method="techcrunch_wp_json_api",
        )

    def _strip_html(self, value: str) -> str:
        text = TAG_RE.sub(" ", value or "")
        return self.clean_text(unescape(text))
