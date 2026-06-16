#!/usr/bin/env python3
"""Yicai ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from .base import BaseAdapter, IngestedItem, dedupe_items


class YicaiAdapter(BaseAdapter):
    source_id = "yicai"
    base_url = "https://www.yicai.com"
    api_endpoints = [
        ("latest", "https://www.yicai.com/api/ajax/getlatest?page=1&pagesize=30"),
        ("featured", "https://www.yicai.com/api/ajax/getAINews?page=1&pagesize=30"),
    ]

    def fetch(self) -> list[IngestedItem]:
        collected: list[IngestedItem] = []
        for section_name, url in self.api_endpoints:
            try:
                payload = json.loads(
                    self.request_text(
                        url,
                        timeout=20,
                    )
                )
            except Exception:
                continue

            if not isinstance(payload, list):
                continue

            for entry in payload:
                item = self._entry_to_item(entry, section_name)
                if item:
                    collected.append(item)

        return dedupe_items(collected)

    def _entry_to_item(self, entry: dict, section_name: str) -> IngestedItem | None:
        title = self.clean_text(str(entry.get("NewsTitle", "")))
        if not title:
            return None

        published_dt = self._parse_datetime(str(entry.get("CreateDate", "")))
        if not published_dt or not self.within_lookback(published_dt):
            return None

        canonical_url = self._resolve_article_url(entry)
        if not canonical_url:
            return None

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=canonical_url,
            canonical_url=canonical_url,
            published_at=published_dt.isoformat(),
            summary=self.clean_text(str(entry.get("NewsNotes", ""))),
            byline=self.clean_text(str(entry.get("NewsAuthor", "") or entry.get("CreaterName", "") or "第一财经")),
            section=section_name,
            discovery_method="yicai_public_ajax",
        )

    def _parse_datetime(self, raw_value: str) -> datetime | None:
        if not raw_value:
            return None
        candidates = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in candidates:
            try:
                parsed = datetime.strptime(raw_value, fmt)
                return parsed.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
            except ValueError:
                continue
        return None

    def _resolve_article_url(self, entry: dict) -> str:
        relative_url = str(entry.get("url", "")).strip()
        if relative_url.startswith("/news/"):
            return self.base_url + relative_url

        article_url = str(entry.get("NewsUrl", "")).strip()
        if article_url:
            return article_url.replace("https://m.yicai.com", self.base_url)
        return ""
