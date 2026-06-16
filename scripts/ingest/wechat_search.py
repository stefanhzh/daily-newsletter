#!/usr/bin/env python3
"""WeChat public-account article search adapter via Sogou or configurable feed."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from urllib.parse import quote

from .base import BaseAdapter, IngestedItem, dedupe_items


class WeChatSearchAdapter(BaseAdapter):
    source_id = "wechat-search"

    def fetch(self) -> list[IngestedItem]:
        keywords = [k.strip() for k in os.environ.get("WECHAT_KEYWORDS", "").split(",") if k.strip()]
        if not keywords:
            return []
        collected: list[IngestedItem] = []
        for keyword in keywords[:10]:
            collected.extend(self._search_keyword(keyword))
        return dedupe_items(collected)

    def _search_keyword(self, keyword: str) -> list[IngestedItem]:
        url = f"https://weixin.sogou.com/weixin?type=2&query={quote(keyword)}&ie=utf8"
        try:
            html = self.request_text(url, timeout=20)
        except Exception:
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        items: list[IngestedItem] = []
        for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            href, title_html = match.groups()
            title = self.clean_text(re.sub(r"<[^>]+>", "", title_html))
            if not title or ("weixin.qq.com" not in href and "sogou.com" not in href):
                continue
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=href,
                    canonical_url=href,
                    published_at=now_iso,
                    summary=f"keyword={keyword}",
                    byline="WeChat/Sogou",
                    section="keyword_search",
                    discovery_method="sogou_weixin_search",
                    fulltext_status="partial_only",
                    fulltext_note="search_result_only_article_page_required",
                )
            )
            if len(items) >= 10:
                break
        return items
