#!/usr/bin/env python3
"""Wind News ingestion adapter."""

from __future__ import annotations

from bs4 import BeautifulSoup
from datetime import datetime

from .base import BaseAdapter, IngestedItem, dedupe_items


class WindNewsAdapter(BaseAdapter):
    source_id = "wind-news"
    news_index_url = "https://www.wind.com.cn/portal/zh/News/index.html"
    list_url = "https://www.wind.com.cn/Wind.Portal.App/windNews/fetchCommonNewsWithoutHeaderNews?pageNum=1&pageSize=20"
    detail_url = "https://www.wind.com.cn/Wind.Portal.App/windNews/fetchNewsDetail?newsObjId={news_id}&docLan=zh"

    def fetch(self) -> list[IngestedItem]:
        session = self._build_session()
        try:
            session.get(self.news_index_url, timeout=20)
            response = session.post(self.list_url, timeout=20)
            payload = response.json()
        except Exception:
            return []

        rows = payload.get("data", {}).get("pageData", [])
        if not isinstance(rows, list):
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            item = self._row_to_item(session, row)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _build_session(self):
        import requests

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Referer": self.news_index_url,
                "Origin": "https://www.wind.com.cn",
                "wind-language": "zh",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        return session

    def _row_to_item(self, session, row: dict[str, object]) -> IngestedItem | None:
        news_id = str(row.get("id", "")).strip()
        title = self.clean_text(str(row.get("title", "")))
        raw_date = str(row.get("date", "")).strip()
        if not news_id or not title or not raw_date:
            return None

        try:
            published_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            return None
        if not self.within_lookback(published_dt):
            return None

        detail = self._fetch_detail(session, news_id)
        content_html = str(detail.get("content", "") or "")
        body_text = self._html_to_text(content_html)
        summary = self.clean_text(str(detail.get("newsAbstract", "") or "")) or (body_text.split("\n\n", 1)[0] if body_text else "")

        canonical_url = f"https://www.wind.com.cn/portal/zh/News/newsDetail.html?id={news_id}"
        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=canonical_url,
            canonical_url=canonical_url,
            published_at=published_dt.isoformat(),
            summary=summary[:320],
            byline="Wind资讯",
            section="news",
            discovery_method="wind_news_ajax",
            body_text=body_text,
            fulltext_note="detail_api_content_html" if body_text else "summary_only",
        )

    def _fetch_detail(self, session, news_id: str) -> dict[str, object]:
        try:
            response = session.post(self.detail_url.format(news_id=news_id), timeout=20)
            payload = response.json()
        except Exception:
            return {}
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def _html_to_text(self, html_fragment: str) -> str:
        if not html_fragment:
            return ""
        soup = BeautifulSoup(html_fragment, "html.parser")
        for node in soup.select("script, style, img, figure, iframe, aside"):
            node.decompose()
        paragraphs: list[str] = []
        for node in soup.find_all(["p", "li", "h2", "h3", "blockquote"]):
            text = self.clean_text(node.get_text(" ", strip=True))
            if len(text) >= 6:
                paragraphs.append(text)
        deduped: list[str] = []
        for paragraph in paragraphs:
            if deduped and deduped[-1] == paragraph:
                continue
            deduped.append(paragraph)
        return "\n\n".join(deduped)
