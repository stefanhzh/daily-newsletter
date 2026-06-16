#!/usr/bin/env python3
"""Associated Press ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import re
from urllib.parse import quote

from .base import BaseAdapter, IngestedItem, dedupe_items, parse_rss_items, title_key


class APAdapter(BaseAdapter):
    source_id = "ap"
    max_ranked_candidates_per_page = 25
    max_exact_google_checks = 20
    ranked_pages = [
        ("https://apnews.com/", "homepage_top"),
    ]
    google_queries = [
        "site:apnews.com when:1d",
        "site:apnews.com business when:1d",
        "site:apnews.com world when:1d",
        "site:apnews.com technology when:1d",
        "site:apnews.com china when:1d",
    ]

    def fetch(self) -> list[IngestedItem]:
        self._exact_google_cache: dict[str, dict[str, str] | None] = {}
        self._exact_google_checks = 0
        enrichment_map = self._fetch_google_enrichment()
        collected: list[IngestedItem] = []
        for page_url, rank_section in self.ranked_pages:
            try:
                page_html = self.request_text(page_url)
            except Exception:
                continue
            collected.extend(self._parse_ranked_page(page_html, page_url, rank_section, enrichment_map))
        return dedupe_items(collected)

    def _fetch_google_enrichment(self) -> dict[str, dict[str, str]]:
        enrichment_map: dict[str, dict[str, str]] = {}
        for query in self.google_queries:
            feed_url = "https://news.google.com/rss/search?q=" + quote(query)
            try:
                xml_text = self.request_text(feed_url)
            except Exception:
                continue

            for entry in parse_rss_items(xml_text)[:50]:
                raw_title = self.clean_text(entry.get("title", ""))
                if " - AP News" not in raw_title:
                    continue
                clean_title = raw_title.replace(" - AP News", "").strip()
                published = entry.get("pubDate", "")
                if not published:
                    continue
                published_iso = self.normalize_published_at(published)
                published_dt = datetime.fromisoformat(published_iso)
                if not self.within_lookback(published_dt):
                    continue
                enrichment_map[title_key(clean_title)] = {
                    "published_at": published_iso,
                    "summary": self._extract_description(entry.get("description", "")),
                    "google_url": entry.get("link", ""),
                }
        return enrichment_map

    def _parse_ranked_page(
        self,
        html: str,
        page_url: str,
        rank_section: str,
        enrichment_map: dict[str, dict[str, str]],
    ) -> list[IngestedItem]:
        fallback_section = self._fallback_section_from_page(page_url)
        items: list[IngestedItem] = []
        title_by_url = self._extract_title_by_url(html)

        for rank_position, article_url in self._extract_ranked_urls(html)[: self.max_ranked_candidates_per_page]:
            title = title_by_url.get(article_url, "")
            if not title:
                continue

            enrichment = enrichment_map.get(title_key(title))
            google_verified = bool(enrichment)
            if not enrichment:
                enrichment = self._fetch_google_title_enrichment(title)
                google_verified = bool(enrichment)
            article_meta = self._fetch_article_metadata(
                article_url,
                fallback_section=fallback_section,
                title=title,
                summary=enrichment["summary"] if enrichment else "",
            )
            if not enrichment:
                enrichment = {
                    "published_at": article_meta.get("published_at") or datetime.now(timezone.utc).isoformat(),
                    "summary": article_meta.get("summary") or title,
                    "google_url": "",
                }

            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=article_url,
                    canonical_url=article_url,
                    published_at=enrichment["published_at"],
                    summary=enrichment["summary"] or article_meta.get("summary") or title,
                    byline="AP News",
                    section=article_meta.get("section") or fallback_section,
                    discovery_method=(
                        "ap_homepage_ranked+google_verified+article_meta"
                        if google_verified
                        else "ap_homepage_ranked+google_unverified+article_meta"
                    ),
                    fulltext_note="" if google_verified else "low_confidence: google_news_24h_not_matched",
                    rank_position=rank_position,
                    rank_section=rank_section,
                )
            )

        return items

    def _fetch_google_title_enrichment(self, title: str) -> dict[str, str] | None:
        key = title_key(title)
        if key in self._exact_google_cache:
            return self._exact_google_cache[key]
        if self._exact_google_checks >= self.max_exact_google_checks:
            self._exact_google_cache[key] = None
            return None

        self._exact_google_checks += 1
        query = f'site:apnews.com "{title}" when:1d'
        feed_url = "https://news.google.com/rss/search?q=" + quote(query)
        try:
            xml_text = self.request_text(feed_url, timeout=12)
        except Exception:
            self._exact_google_cache[key] = None
            return None

        for entry in parse_rss_items(xml_text)[:8]:
            raw_title = self.clean_text(entry.get("title", ""))
            if " - AP News" not in raw_title:
                continue
            clean_title = raw_title.replace(" - AP News", "").strip()
            if not self._titles_are_related(title, clean_title):
                continue
            published = entry.get("pubDate", "")
            if not published:
                continue
            published_iso = self.normalize_published_at(published)
            published_dt = datetime.fromisoformat(published_iso)
            if not self.within_lookback(published_dt):
                continue
            enrichment = {
                "published_at": published_iso,
                "summary": self._extract_description(entry.get("description", "")) or clean_title,
                "google_url": entry.get("link", ""),
            }
            self._exact_google_cache[key] = enrichment
            return enrichment

        self._exact_google_cache[key] = None
        return None

    def _titles_are_related(self, page_title: str, google_title: str) -> bool:
        page_key = title_key(page_title)
        google_key = title_key(google_title)
        if page_key == google_key or page_key in google_key or google_key in page_key:
            return True
        page_tokens = {token for token in page_key.split() if len(token) > 2}
        google_tokens = {token for token in google_key.split() if len(token) > 2}
        if not page_tokens or not google_tokens:
            return False
        overlap = len(page_tokens & google_tokens)
        return overlap / max(1, min(len(page_tokens), len(google_tokens))) >= 0.65

    def _extract_ranked_urls(self, html: str) -> list[tuple[int, str]]:
        ranked_urls = self._extract_json_ld_ranked_urls(html)
        if not ranked_urls:
            ranked_urls = self._extract_main_article_urls(html)

        seen: set[str] = set()
        deduped: list[tuple[int, str]] = []
        for position, url in ranked_urls:
            if "/article/" not in url or url in seen:
                continue
            seen.add(url)
            deduped.append((position, url))
        return deduped

    def _extract_json_ld_ranked_urls(self, html: str) -> list[tuple[int, str]]:
        ranked_urls: list[tuple[int, str]] = []
        script_pattern = re.compile(
            r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
            re.IGNORECASE | re.DOTALL,
        )
        for match in script_pattern.finditer(html):
            payload = unescape(match.group(1)).strip()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            main_entity = data.get("mainEntity") if isinstance(data, dict) else None
            elements = main_entity.get("itemListElement") if isinstance(main_entity, dict) else None
            if not isinstance(elements, list):
                continue
            for index, element in enumerate(elements, start=1):
                if not isinstance(element, dict):
                    continue
                url = str(element.get("url") or "").strip()
                position = int(element.get("position") or index)
                if url:
                    ranked_urls.append((position, url))
            if ranked_urls:
                break
        return ranked_urls

    def _extract_main_article_urls(self, html: str) -> list[tuple[int, str]]:
        main_start = html.find("<main")
        scoped_html = html[main_start:] if main_start >= 0 else html
        ranked_urls: list[tuple[int, str]] = []
        seen_urls: set[str] = set()
        pattern = re.compile(
            r"<a[^>]+href=['\"](https://apnews\.com/article/[^'\"]+)['\"][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )

        for article_url, inner_html in pattern.findall(scoped_html):
            if article_url in seen_urls:
                continue

            title = self.clean_text(re.sub(r"<[^>]+>", " ", unescape(inner_html)))
            if len(title) < 30 or title.lower() in {"read more", "view all"}:
                continue

            seen_urls.add(article_url)
            ranked_urls.append((len(ranked_urls) + 1, article_url))
        return ranked_urls

    def _extract_title_by_url(self, html: str) -> dict[str, str]:
        titles: dict[str, str] = {}
        pattern = re.compile(
            r"<a[^>]+href=['\"](https://apnews\.com/article/[^'\"]+)['\"][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        for article_url, inner_html in pattern.findall(html):
            title = self.clean_text(re.sub(r"<[^>]+>", " ", unescape(inner_html)))
            if len(title) >= 30 and title.lower() not in {"read more", "view all"}:
                titles.setdefault(article_url, title)
        return titles

    def _fallback_section_from_page(self, page_url: str) -> str:
        if page_url.rstrip("/") == "https://apnews.com":
            return "homepage"
        return page_url.rstrip("/").rsplit("/", 1)[-1]

    def _extract_description(self, html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet or "")
        text = self.clean_text(unescape(text))
        text = re.sub(r"\s+AP News$", "", text).strip()
        return text

    def _fetch_article_native_section(
        self,
        article_url: str,
        *,
        fallback_section: str,
        title: str,
        summary: str,
    ) -> str:
        return self._fetch_article_metadata(
            article_url,
            fallback_section=fallback_section,
            title=title,
            summary=summary,
        ).get("section", fallback_section)

    def _fetch_article_metadata(
        self,
        article_url: str,
        *,
        fallback_section: str,
        title: str,
        summary: str,
    ) -> dict[str, str]:
        try:
            html = self.request_text(article_url, timeout=10)
        except Exception:
            return {
                "section": self._choose_native_section([], [], fallback_section, title, summary),
                "published_at": "",
                "summary": summary,
            }

        sections = self._extract_meta_values(html, "article:section")
        tags = self._extract_meta_values(html, "article:tag")
        article_summary = (
            self._extract_first_meta_value(html, "og:description")
            or self._extract_first_meta_value(html, "description")
            or summary
        )
        published_at = (
            self._extract_first_meta_value(html, "article:published_time")
            or self._extract_first_meta_value(html, "article:modified_time")
            or self._extract_first_meta_value(html, "date")
        )
        return {
            "section": self._choose_native_section(sections, tags, fallback_section, title, article_summary),
            "published_at": self._normalize_meta_datetime(published_at),
            "summary": article_summary,
        }

    def _extract_first_meta_value(self, html: str, property_name: str) -> str:
        values = self._extract_meta_values(html, property_name)
        return values[0] if values else ""

    def _normalize_meta_datetime(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    def _extract_meta_values(self, html: str, property_name: str) -> list[str]:
        values: list[str] = []
        patterns = [
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(property_name)}["\']',
        ]
        for pattern in patterns:
            for value in re.findall(pattern, html, re.IGNORECASE):
                clean_value = self.clean_text(value)
                if clean_value and clean_value not in values:
                    values.append(clean_value)
        return values

    def _choose_native_section(
        self,
        sections: list[str],
        tags: list[str],
        fallback_section: str,
        title: str,
        summary: str,
    ) -> str:
        labels = " ".join([*sections, *tags, title, summary]).lower()

        if "tariff" in labels or "trade war" in labels:
            return "business/tariffs"
        if any(term in labels for term in ("inflation", "consumer prices", "interest rate", "interest rates", "deficit", "bond market")):
            return "business/inflation"
        if any(term in labels for term in ("financial markets", "stock market", "wall street", "stocks", "bonds", "treasury yields")):
            return "business/financial markets"
        if any(term in labels for term in ("science", "clinical trial", "drug", "medicine", "cancer", "health")):
            return "science"
        if any(term in labels for term in ("technology", "tech", "artificial intelligence", " ai ")):
            return "business-technology"

        normalized_sections = [self._normalize_label(value) for value in sections]
        for section in normalized_sections:
            if section in {"world news", "world"}:
                return "world"
            if section in {"u.s. news", "us news", "us"}:
                return "us"
            if section == "politics":
                return "politics"
            if section == "business":
                return "business"
            if section:
                return section
        return fallback_section

    def _normalize_label(self, value: str) -> str:
        normalized = self.clean_text(value).lower()
        normalized = normalized.replace("&amp;", "&")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
