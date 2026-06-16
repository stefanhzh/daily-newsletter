#!/usr/bin/env python3
"""WallstreetCN ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from html import unescape

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class WallstreetCNAdapter(BaseAdapter):
    source_id = "wallstreetcn"
    flow_url = "https://api-one-wscn.awtmt.com/apiv1/content/information-flow?channel=global-channel&limit=50"
    detail_url = "https://api-one-wscn.awtmt.com/apiv1/content/articles/{article_id}?extract=0"

    def fetch(self) -> list[IngestedItem]:
        try:
            payload = json.loads(self.request_text(self.flow_url))
        except Exception:
            return []

        rows = payload.get("data", {}).get("items", [])
        if not isinstance(rows, list):
            return []

        collected: list[IngestedItem] = []
        for row in rows:
            resource = row.get("resource", {})
            item = self._resource_to_item(resource)
            if item is not None:
                collected.append(item)
        return dedupe_items(collected)

    def _resource_to_item(self, resource: dict[str, object]) -> IngestedItem | None:
        title = self.clean_text(str(resource.get("title", "")))
        uri = str(resource.get("uri", "")).strip()
        article_id = resource.get("id")
        if not title or not uri or not article_id:
            return None
        if not ("/articles/" in uri or "/member/articles/" in uri):
            return None

        try:
            published_dt = datetime.fromtimestamp(int(resource.get("display_time", 0)), tz=timezone.utc)
        except Exception:
            return None
        if not self.within_lookback(published_dt):
            return None

        detail = self._fetch_detail(int(article_id))
        summary = self.clean_text(str(resource.get("content_short", "") or detail.get("content_short", "")))
        body_text = self._html_to_text(str(detail.get("content", "")))
        if not summary and body_text:
            summary = body_text.split("\n\n", 1)[0][:320]

        byline = self.clean_text(str(resource.get("source_name", "") or detail.get("source_name", "") or "华尔街见闻"))
        section = "member" if "/member/" in uri else "article"
        note = "detail_api_content_html" if body_text else "summary_only"

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=uri,
            canonical_url=uri,
            published_at=published_dt.isoformat(),
            summary=summary[:320],
            byline=byline,
            section=section,
            discovery_method="wallstreetcn_information_flow_api",
            body_text=body_text,
            fulltext_note=note,
        )

    def _fetch_detail(self, article_id: int) -> dict[str, object]:
        try:
            payload = json.loads(self.request_text(self.detail_url.format(article_id=article_id)))
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
        for node in soup.find_all(["p", "li", "h2", "h3"]):
            text = self.clean_text(unescape(node.get_text(" ", strip=True)))
            if len(text) >= 12:
                paragraphs.append(text)
        deduped: list[str] = []
        for paragraph in paragraphs:
            if deduped and deduped[-1] == paragraph:
                continue
            deduped.append(paragraph)
        return "\n\n".join(deduped)
