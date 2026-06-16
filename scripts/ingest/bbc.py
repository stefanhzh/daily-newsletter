#!/usr/bin/env python3
"""BBC ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items


class BBCAdapter(BaseAdapter):
    source_id = "bbc"
    homepage_url = "https://www.bbc.com/news"
    max_links_per_rank_page = 12
    max_collected_items = 30
    rank_pages = [
        ("news_homepage", "https://www.bbc.com/news"),
        ("business_homepage", "https://www.bbc.com/business"),
        ("technology_homepage", "https://www.bbc.com/innovation/technology"),
    ]
    feeds = [
        ("news", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ]

    def fetch(self) -> list[IngestedItem]:
        feed_items_by_url = self._fetch_feed_index()
        collected: list[IngestedItem] = []
        seen_urls: set[str] = set()

        for rank_section, page_url in self.rank_pages:
            for position, url in enumerate(self._ranked_links(page_url), start=1):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                item = self._build_ranked_item(
                    url=url,
                    rank_position=position,
                    rank_section=rank_section,
                    feed_item=feed_items_by_url.get(url),
                )
                if item:
                    collected.append(item)
                if len(collected) >= self.max_collected_items:
                    return dedupe_items(collected)

        return dedupe_items(collected)

    def _fetch_feed_index(self) -> dict[str, IngestedItem]:
        indexed: dict[str, IngestedItem] = {}
        for section_name, feed_url in self.feeds:
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue
            for entry in parse_rss_items(xml_text)[:40]:
                item = self._entry_to_item(entry, section_name)
                if item:
                    indexed.setdefault(self._canonicalize_url(item.canonical_url), item)
        return indexed

    def _ranked_links(self, page_url: str) -> list[str]:
        try:
            html = self.request_text(page_url, timeout=30)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        seen_urls: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            url = self._canonicalize_url(urljoin(page_url, anchor.get("href", "").strip()))
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not self._is_supported_url(url) or url in seen_urls or len(title) < 12:
                continue
            seen_urls.add(url)
            links.append(url)
            if len(links) >= self.max_links_per_rank_page:
                break
        return links

    def _build_ranked_item(
        self,
        *,
        url: str,
        rank_position: int,
        rank_section: str,
        feed_item: IngestedItem | None,
    ) -> IngestedItem | None:
        detail = self._fetch_detail(url)
        if not detail:
            return None

        published_at = feed_item.published_at if feed_item else detail.get("published_at", "")
        published_dt = self._parse_iso_datetime(published_at)
        if not published_dt or not self.within_lookback(published_dt):
            return None

        media_kind = self._media_kind(url)
        body_text = str(detail.get("body_text", ""))
        summary = self.clean_text(feed_item.summary if feed_item and feed_item.summary else str(detail.get("summary", "")))
        if media_kind and not self._has_enough_media_text(summary, body_text):
            return None

        tags = [str(tag) for tag in detail.get("tags", []) if str(tag).strip()]
        note_parts = []
        if media_kind:
            note_parts.append(f"{media_kind}_text_summary")
        if tags:
            note_parts.append("source_tags=" + "|".join(tags))

        return IngestedItem(
            source_id=self.source_id,
            title=self.clean_text(str(detail.get("title") or (feed_item.title if feed_item else ""))),
            source_url=url,
            canonical_url=url,
            published_at=published_at,
            summary=summary,
            byline="BBC",
            section=self.clean_text(str(detail.get("section", ""))),
            discovery_method="bbc_homepage_ranked_html+article_detail",
            body_text=body_text,
            fulltext_status="fulltext" if body_text else "summary_only",
            fulltext_note="; ".join(note_parts),
            rank_position=rank_position,
            rank_section=rank_section,
            source_tags=tags,
        )

    def _fetch_detail(self, url: str) -> dict[str, object] | None:
        try:
            html = self.request_text(url, timeout=30)
        except Exception:
            return None

        soup = BeautifulSoup(html, "html.parser")
        title = self._first_text(soup, ["h1"])
        summary = self._meta_content(soup, "description")
        published_at = (
            self._meta_content(soup, "article:published_time")
            or self._meta_content(soup, "article:modified_time")
            or self._meta_content(soup, "last-modified")
        )
        published_at = self._normalize_iso(published_at)
        section = self._native_section(soup)
        tags = self._topic_tags(soup)
        body_text = self._body_text(soup)

        if not title or not published_at:
            return None

        return {
            "title": title,
            "summary": summary,
            "published_at": published_at,
            "section": section,
            "tags": tags,
            "body_text": body_text,
        }

    def _native_section(self, soup: BeautifulSoup) -> str:
        subsection = self._meta_content(soup, "page.subsection")
        section = self._meta_content(soup, "page.section")
        if subsection and subsection.lower() != section.lower():
            return self._normalize_native_label(subsection)
        return self._normalize_native_label(section)

    def _topic_tags(self, soup: BeautifulSoup) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if not (href.startswith("/news/topics/") or href.startswith("/news/world/")):
                continue
            if anchor.get("data-testid") != "internal-link":
                continue
            tag = self.clean_text(anchor.get_text(" ", strip=True))
            if not tag or tag.lower() in seen:
                continue
            seen.add(tag.lower())
            tags.append(tag)
        return tags[:8]

    def _body_text(self, soup: BeautifulSoup) -> str:
        paragraphs: list[str] = []
        for paragraph in soup.find_all("p"):
            text = self.clean_text(paragraph.get_text(" ", strip=True))
            if len(text) < 30:
                continue
            lower = text.lower()
            if lower.startswith(("follow bbc", "listen to", "watch:")):
                continue
            paragraphs.append(text)
        return "\n\n".join(paragraphs[:80])

    def _is_supported_url(self, url: str) -> bool:
        return bool(
            re.match(r"^https://www\.bbc\.com/news/articles/[a-z0-9]+$", url)
            or re.match(r"^https://www\.bbc\.com/news/videos/[a-z0-9]+$", url)
            or re.match(r"^https://www\.bbc\.com/audio/play/[a-z0-9]+$", url)
        )

    def _media_kind(self, url: str) -> str:
        if "/news/videos/" in url:
            return "video"
        if "/audio/play/" in url:
            return "audio"
        return ""

    def _has_enough_media_text(self, summary: str, body_text: str) -> bool:
        return len(summary) >= 40 or len(body_text) >= 120

    def _canonicalize_url(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))

    def _entry_to_item(self, entry: dict[str, str], section_name: str) -> IngestedItem | None:
        title = self.clean_text(entry.get("title", ""))
        link = self._canonicalize_url(entry.get("link", "").strip())
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
            summary=self.clean_text(entry.get("description", "")),
            byline="BBC",
            section=section_name,
            discovery_method="bbc_official_rss_metadata",
        )

    def _first_text(self, soup: BeautifulSoup, selectors: list[str]) -> str:
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return self.clean_text(node.get_text(" ", strip=True))
        return ""

    def _meta_content(self, soup: BeautifulSoup, key: str) -> str:
        node = soup.find("meta", attrs={"name": key}) or soup.find("meta", attrs={"property": key})
        return self.clean_text(node.get("content", "")) if node else ""

    def _normalize_iso(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        value = raw_value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
        except ValueError:
            return ""

    def _parse_iso_datetime(self, raw_value: str) -> datetime | None:
        if not raw_value:
            return None
        try:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    def _normalize_native_label(self, value: str) -> str:
        return self.clean_text(value.replace("_", " "))
