#!/usr/bin/env python3
"""Tonghuashun Finance hot-rank ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from bs4 import BeautifulSoup
import requests

from .base import BaseAdapter, IngestedItem, dedupe_items


class THSHotrankAdapter(BaseAdapter):
    source_id = "ths-hotrank"
    hotrank_url = "https://www.10jqka.com.cn/index.html"

    def fetch(self) -> list[IngestedItem]:
        try:
            response = requests.get(
                self.hotrank_url,
                timeout=20,
                headers={"User-Agent": self.user_agent},
            )
            response.encoding = response.apparent_encoding or "gb18030"
            html = response.text
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        now_iso = datetime.now(timezone.utc).isoformat()
        collected: list[IngestedItem] = []

        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            title = self.clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            rank = self._parse_rank(anchor)
            rank_section = self._infer_rank_section(anchor, href)
            if not href or href == "###" or not title or rank <= 0:
                continue
            if "10jqka.com.cn/20" not in href or not href.endswith(".shtml"):
                continue
            if not re.search(r"/20\d{6}/c\d+\.shtml$", href):
                continue

            collected.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=href,
                    canonical_url=href,
                    published_at=now_iso,
                    summary=f"Tonghuashun Finance ranked item, position {rank}.",
                    byline="Tonghuashun Finance",
                    section=rank_section,
                    discovery_method="index_hotrank_html",
                    fulltext_note="ranking_surface_with_downstream_article",
                    rank_position=rank,
                    rank_section=rank_section,
                )
            )

        return dedupe_items(collected)

    def _parse_rank(self, anchor: BeautifulSoup) -> int:
        rel = anchor.get("rel")
        if isinstance(rel, list) and rel:
            raw = rel[0]
        else:
            raw = rel or ""
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return 0

    def _infer_rank_section(self, anchor: BeautifulSoup, href: str) -> str:
        for parent in anchor.parents:
            classes = set(parent.get("class", []))
            parent_text = self.clean_text(parent.get_text(" ", strip=True))
            if "toutiao" in classes:
                return "headline"
            if "rec-login" in classes or "tab-container" in classes:
                if any(token in parent_text for token in ["重要", "快讯", "投资机会"]):
                    return "important_flash"
            if "newhe" in classes:
                return "important_flash"
            if "last" in classes:
                return "flash"

        if "goodsfu.10jqka.com.cn" in href:
            return "commodity_market"
        if "field.10jqka.com.cn" in href:
            return "sector_rank"
        if "stock.10jqka.com.cn" in href:
            return "stock_news"
        if "news.10jqka.com.cn" in href:
            return "finance_news"
        return "homepage_rank"
