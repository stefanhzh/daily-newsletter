#!/usr/bin/env python3
"""Caixin Global ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items, extract_meta_content, parse_rss_items, title_key


ARTICLE_URL_RE = re.compile(r"https://www\.caixinglobal\.com/\d{4}-\d{2}-\d{2}/[^\"]+\.html")
TITLE_TAG_RE = re.compile(r"<title>([^<]+)</title>", re.I)
BYLINE_RE = re.compile(r'(?:"author"|name="author")\s+content="([^"]+)"', re.I)


class CaixinAdapter(BaseAdapter):
    source_id = "caixin"
    homepage_url = "https://www.caixinglobal.com/"
    search_api = "https://mapi.caixinglobal.com/api/search.jsp?callback=cb&keyword={keyword}&page=1&size=5"
    section_urls = {
        "world": "https://www.caixinglobal.com/world/",
        "economy": "https://www.caixinglobal.com/economy/",
        "china": "https://www.caixinglobal.com/china/",
        "finance": "https://www.caixinglobal.com/finance/",
        "business-and-tech": "https://www.caixinglobal.com/business-and-tech/",
        "news": "https://www.caixinglobal.com/news/",
    }
    max_urls_per_section = 2
    max_article_page_requests = 12
    max_search_fallback_items = 5
    homepage_timeout = 10
    section_timeout = 8
    article_timeout = 8
    search_timeout = 10
    native_section_names = {
        "finance",
        "business",
        "business-and-tech",
        "tech",
        "technology",
        "economy",
        "china",
        "world",
        "commentary",
        "analysis",
    }

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        seen_urls: set[str] = set()
        article_page_requests = 0

        try:
            homepage_html = self.request_text(self.homepage_url, timeout=self.homepage_timeout)
        except Exception:
            homepage_html = ""

        if homepage_html:
            for rank_section, article_url, rank_position in self._extract_homepage_ranked_urls(homepage_html):
                if article_url in seen_urls:
                    continue
                if article_page_requests >= self.max_article_page_requests:
                    break
                article_page_requests += 1
                article = self._fetch_and_parse_article(article_url, rank_section, rank_position)
                if article is None:
                    continue
                seen_urls.add(article_url)
                collected.append(article)

        for section_name, section_url in self.section_urls.items():
            if article_page_requests >= self.max_article_page_requests:
                break
            try:
                section_html = self.request_text(section_url, timeout=self.section_timeout)
            except Exception:
                continue

            candidates = self._extract_article_urls(section_html)
            picked = 0
            for rank_position, article_url in enumerate(candidates, start=1):
                if article_url in seen_urls:
                    continue

                # The article path already contains the calendar day; use it as a cheap first-pass filter
                # before we request the article page for full metadata.
                if not self._url_date_within_fallback(article_url):
                    continue

                if article_page_requests >= self.max_article_page_requests:
                    break
                article_page_requests += 1
                article = self._fetch_and_parse_article(article_url, section_name, rank_position)
                if article is None:
                    continue

                seen_urls.add(article_url)
                collected.append(article)
                picked += 1
                if picked >= self.max_urls_per_section:
                    break

        if len(collected) < 12:
            for article in self._fetch_search_fallback(seen_urls, limit=self.max_search_fallback_items):
                seen_urls.add(article.canonical_url)
                collected.append(article)

        return dedupe_items(collected)

    def _fetch_and_parse_article(
        self,
        article_url: str,
        rank_section: str,
        rank_position: int = 0,
    ) -> IngestedItem | None:
        try:
            article_html = self.request_text(article_url, timeout=self.article_timeout)
        except Exception:
            return None
        return self._parse_article(article_html, article_url, rank_section, rank_position)

    def _extract_article_urls(self, html: str) -> list[str]:
        ordered_urls: list[str] = []
        seen_urls: set[str] = set()
        for article_url in ARTICLE_URL_RE.findall(html):
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            ordered_urls.append(article_url)
        return ordered_urls

    def _extract_homepage_ranked_urls(self, html: str) -> list[tuple[str, str, int]]:
        soup = BeautifulSoup(html, "html.parser")
        ranked_urls: list[tuple[str, str, int]] = []
        ranked_urls.extend(self._extract_links_from_box(soup, "TOP STORIES", "top_stories"))
        ranked_urls.extend(self._extract_links_from_box(soup, "MOST POPULAR", "most_popular", limit=5))
        return ranked_urls

    def _extract_links_from_box(
        self,
        soup: BeautifulSoup,
        title_text: str,
        rank_section: str,
        *,
        limit: int | None = None,
    ) -> list[tuple[str, str, int]]:
        if rank_section == "top_stories":
            preferred_box = soup.select_one("div.top-stories-box")
            if preferred_box is not None:
                links = self._extract_unique_article_links(preferred_box)
                if limit is not None:
                    links = links[:limit]
                return [(rank_section, url, rank) for rank, url in enumerate(links, start=1)]
        if rank_section == "most_popular":
            preferred_box = soup.select_one("div.popular")
            if preferred_box is not None:
                links = self._extract_unique_article_links(preferred_box)
                if limit is not None:
                    links = links[:limit]
                return [(rank_section, url, rank) for rank, url in enumerate(links, start=1)]

        title_node = soup.find(string=re.compile(re.escape(title_text), re.I))
        if title_node is None:
            return []

        box = title_node.parent
        for _ in range(6):
            if box is None:
                return []
            links = self._extract_unique_article_links(box)
            if links:
                if limit is not None:
                    links = links[:limit]
                return [(rank_section, url, rank) for rank, url in enumerate(links, start=1)]
            box = box.parent
        return []

    def _extract_unique_article_links(self, node) -> list[str]:
        urls: list[str] = []
        seen_urls: set[str] = set()
        for anchor in node.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://www.caixinglobal.com" + href
            href = href.split("?", 1)[0]
            if not ARTICLE_URL_RE.fullmatch(href):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            urls.append(href)
        return urls

    def _url_date_within_fallback(self, article_url: str) -> bool:
        match = re.search(r"/(\d{4})-(\d{2})-(\d{2})/", article_url)
        if not match:
            return True
        try:
            article_day = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return True

        now = datetime.now(timezone.utc)
        horizon_days = max(2, (self.lookback_hours // 24) + 1)
        return article_day >= now.replace(hour=0, minute=0, second=0, microsecond=0) - self._timedelta_days(horizon_days)

    def _timedelta_days(self, days: int):
        from datetime import timedelta

        return timedelta(days=days)

    def _parse_article(
        self,
        html: str,
        article_url: str,
        rank_section: str,
        rank_position: int = 0,
    ) -> IngestedItem | None:
        published_dt = self._extract_published_at(html)
        if not published_dt or not self.within_lookback(published_dt):
            return None

        title = self._extract_title(html)
        if not title:
            return None

        summary = self._extract_summary(html)
        byline = self._extract_byline(html)
        source_tags = self._extract_source_tags(html)
        native_section = self._extract_native_section(source_tags, title)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=article_url,
            canonical_url=article_url,
            published_at=published_dt.isoformat(),
            summary=summary,
            byline=byline or "Caixin Global",
            section=native_section,
            discovery_method=(
                "caixin_homepage_ranked_html+article_page"
                if rank_section in {"top_stories", "most_popular"}
                else "caixin_section_page+article_page"
            ),
            rank_position=rank_position,
            rank_section=rank_section if rank_position else "",
            source_tags=source_tags,
        )

    def _fetch_search_fallback(self, seen_urls: set[str], *, limit: int) -> list[IngestedItem]:
        query_url = self._google_news_query_url()
        try:
            rss_text = self.request_text(query_url, timeout=self.search_timeout)
        except Exception:
            return []

        items: list[IngestedItem] = []
        seen_titles: set[str] = set()
        for rss_item in parse_rss_items(rss_text)[:15]:
            raw_title = self.clean_text(rss_item.get("title", ""))
            title = re.sub(r"\s*-\s*Caixin Global$", "", raw_title, flags=re.I)
            key = title_key(title)
            if not title or key in seen_titles:
                continue
            seen_titles.add(key)

            article = self._search_api_lookup(title, seen_urls)
            if article is None:
                continue
            items.append(article)
            if len(items) >= limit:
                break

        return items

    def _google_news_query_url(self) -> str:
        lookback_days = max(1, min(7, (self.lookback_hours + 23) // 24))
        query = quote(f"site:caixinglobal.com when:{lookback_days}d")
        return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    def _search_api_lookup(self, title: str, seen_urls: set[str]) -> IngestedItem | None:
        try:
            payload = self.request_text(self.search_api.format(keyword=quote(title)), timeout=self.search_timeout)
        except Exception:
            return None

        data = self._parse_jsonp_payload(payload)
        rows = (((data or {}).get("data") or {}).get("list") or [])
        title_norm = title_key(title)

        for row in rows:
            article_url = row.get("link", "")
            if (
                not article_url.startswith("https://www.caixinglobal.com/")
                or article_url in seen_urls
            ):
                continue

            candidate_title = self.clean_text(row.get("title", ""))
            if title_key(candidate_title) != title_norm:
                # The search API can return loosely related results; keep only exact title hits.
                continue

            try:
                article_html = self.request_text(article_url, timeout=self.article_timeout)
            except Exception:
                continue

            article = self._parse_article(article_html, article_url, row.get("subject", "").lower() or "search")
            if article is None:
                continue

            if row.get("author"):
                article.byline = self.clean_text(row["author"])
            if row.get("leadin"):
                article.summary = self.clean_text(row["leadin"])
            article.discovery_method = "caixin_google_news_title+search_api"
            return article

        return None

    def _parse_jsonp_payload(self, payload: str) -> dict | None:
        payload = (payload or "").strip()
        match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", payload, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _extract_title(self, html: str) -> str:
        for key in ("twitter:title", "og:title"):
            value = extract_meta_content(html, key)
            if value:
                return self._normalize_caixin_text(value)
        match = TITLE_TAG_RE.search(html)
        if not match:
            return ""
        title = unescape(match.group(1)).replace(" - Caixin Global", "")
        return self._normalize_caixin_text(title)

    def _extract_summary(self, html: str) -> str:
        for key in ("description", "twitter:description", "og:description"):
            value = extract_meta_content(html, key)
            if value:
                return self._normalize_caixin_text(value)
        return ""

    def _extract_byline(self, html: str) -> str:
        meta_author = extract_meta_content(html, "author")
        if meta_author:
            return self._normalize_caixin_text(meta_author)
        match = BYLINE_RE.search(html)
        if not match:
            return ""
        return self._normalize_caixin_text(unescape(match.group(1)))

    def _extract_source_tags(self, html: str) -> list[str]:
        tags: list[str] = []
        entity = self._extract_entity_payload(html)
        tag_names = str(entity.get("tagNames", "") or "")
        for raw_tag in tag_names.split(","):
            tag = self._normalize_caixin_text(raw_tag)
            if tag and tag not in tags:
                tags.append(tag)
        return tags

    def _extract_native_section(self, source_tags: list[str], title: str) -> str:
        for tag in source_tags:
            normalized = tag.lower().strip().replace(" ", "-")
            if normalized in self.native_section_names:
                return normalized
        lowered_title = title.lower()
        if lowered_title.startswith("commentary:"):
            return "commentary"
        if lowered_title.startswith("analysis:"):
            return "analysis"
        return ""

    def _extract_entity_payload(self, html: str) -> dict:
        match = re.search(r"var\s+entity\s*=\s*(\{.*?\})\s*</script>", html, re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}

    def _extract_published_at(self, html: str) -> datetime | None:
        match = re.search(r"Published:\s*([^<]+)", html, re.I)
        if not match:
            return None
        raw_value = self.clean_text(unescape(match.group(1)))
        raw_value = raw_value.replace("a.m.", "AM").replace("p.m.", "PM")
        raw_value = raw_value.replace("GMT+8", "+0800")
        raw_value = raw_value.replace("May.", "May").replace("Jun.", "Jun").replace("Jul.", "Jul")
        raw_value = raw_value.replace("Aug.", "Aug").replace("Sep.", "Sep").replace("Oct.", "Oct")
        raw_value = raw_value.replace("Nov.", "Nov").replace("Dec.", "Dec")
        try:
            parsed = datetime.strptime(raw_value, "%b %d, %Y %I:%M %p %z")
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc)

    def _normalize_caixin_text(self, value: str) -> str:
        cleaned = self.clean_text(value)
        replacements = {
            "ĄŻ": "’",
            "ĄŽ": "‘",
            "鈥榗": "“c",
            "鈥?": "”",
        }
        for src, dst in replacements.items():
            cleaned = cleaned.replace(src, dst)
        return cleaned
