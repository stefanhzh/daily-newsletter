#!/usr/bin/env python3
"""GitHub Trending ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class GitHubTrendingAdapter(BaseAdapter):
    source_id = "github-trending"
    trending_url = "https://github.com/trending?since=daily"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.trending_url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("article.Box-row")
        if not cards:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        collected: list[IngestedItem] = []
        for card in cards[:25]:
            item = self._card_to_item(card, now_iso)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _card_to_item(self, card: BeautifulSoup, published_at: str) -> IngestedItem | None:
        repo_link = card.select_one("h2 a")
        if repo_link is None:
            return None

        repo_path = (repo_link.get("href") or "").strip()
        repo_name = self.clean_text(repo_link.get_text(" ", strip=True)).replace(" / ", "/")
        if not repo_path or not repo_name:
            return None

        description_node = card.select_one("p")
        language_node = card.select_one("[itemprop='programmingLanguage']")
        star_node = card.select_one("a[href$='/stargazers']")

        description = self.clean_text(description_node.get_text(" ", strip=True)) if description_node else ""
        language = self.clean_text(language_node.get_text(" ", strip=True)) if language_node else ""
        stars_total = self.clean_text(star_node.get_text(" ", strip=True)) if star_node else ""

        stars_today = ""
        for node in card.select("span, div"):
            text = self.clean_text(node.get_text(" ", strip=True))
            if "stars today" in text.lower():
                stars_today = text
                break

        summary_parts = [part for part in [description, language, stars_total and f"Total stars: {stars_total}", stars_today] if part]
        summary = self._normalize_summary(" | ".join(summary_parts))

        owner = repo_name.split("/", 1)[0] if "/" in repo_name else "GitHub"
        repo_url = urljoin("https://github.com", repo_path)
        return IngestedItem(
            source_id=self.source_id,
            title=repo_name,
            source_url=repo_url,
            canonical_url=repo_url,
            published_at=published_at,
            summary=summary[:400].strip(),
            byline=owner,
            section="daily",
            discovery_method="github_trending_html",
            body_text="",
            fulltext_note="ranking_page_no_article_body",
        )

    def _normalize_summary(self, value: str) -> str:
        replacements = {
            "鈫?": "->",
            "Ўъ": "->",
            "蟺": "",
            "鈥?": "-",
            "–": "-",
            "—": "-",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return self.clean_text(value)
