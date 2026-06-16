#!/usr/bin/env python3
"""Cailian Press ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from .base import BaseAdapter, IngestedItem, dedupe_items


class CailianAdapter(BaseAdapter):
    source_id = "cailian"
    homepage_url = "https://www.cls.cn/"
    ignored_source_tags = {"原创", "独家", "文章", "财联社"}

    def fetch(self) -> list[IngestedItem]:
        html = self.request_text(self.homepage_url)
        state = self._extract_next_data(html)
        index_page = self._extract_index_page(state)

        collected: list[IngestedItem] = []
        collected.extend(self._from_hot_articles(index_page.get("hotArticleData", []), "hot_article"))
        assemble_data = index_page.get("assembleData", {})
        collected.extend(self._from_assemble_list(assemble_data.get("top_article", []), "top_article"))
        collected.extend(self._from_assemble_list(assemble_data.get("depth_list", []), "depth_list"))
        return dedupe_items(collected)

    def _extract_next_data(self, html: str) -> dict:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not match:
            raise ValueError("Could not find Cailian __NEXT_DATA__ payload")
        return json.loads(match.group(1))

    def _extract_index_page(self, state: dict) -> dict:
        props = state.get("props", {})
        page_props = props.get("pageProps", {})
        if page_props:
            return page_props
        initial_state = props.get("initialState", {})
        return initial_state.get("indexPage", {})

    def _from_hot_articles(self, items: list[dict], section_name: str) -> list[IngestedItem]:
        converted: list[IngestedItem] = []
        for rank, entry in enumerate(items, start=1):
            item = self._build_item(
                article_id=entry.get("id"),
                title=entry.get("title", ""),
                summary=entry.get("brief", ""),
                timestamp=entry.get("ctime"),
                byline=entry.get("author") or "Cailian Press",
                section_name=section_name,
                external_link="",
                rank_position=rank,
                source_tags=self._extract_source_tags(entry),
            )
            if item:
                converted.append(item)
        return converted

    def _from_assemble_list(self, items: list[dict], section_name: str) -> list[IngestedItem]:
        converted: list[IngestedItem] = []
        for rank, entry in enumerate(items, start=1):
            item = self._build_item(
                article_id=entry.get("id"),
                title=entry.get("title", ""),
                summary=entry.get("brief", ""),
                timestamp=entry.get("ctime"),
                byline=entry.get("author") or entry.get("source") or "Cailian Press",
                section_name=section_name,
                external_link=entry.get("external_link", ""),
                rank_position=rank,
                source_tags=self._extract_source_tags(entry),
            )
            if item:
                converted.append(item)
        return converted

    def _build_item(
        self,
        *,
        article_id: int | str | None,
        title: str,
        summary: str,
        timestamp: int | str | None,
        byline: str,
        section_name: str,
        external_link: str,
        rank_position: int,
        source_tags: list[str],
    ) -> IngestedItem | None:
        clean_title = self.clean_text(title)
        if not article_id or not clean_title or external_link:
            return None
        published_dt = self._normalize_epoch(timestamp)
        if not published_dt or not self.within_lookback(published_dt):
            return None

        canonical_url = f"https://www.cls.cn/detail/{article_id}"
        if not source_tags:
            source_tags = self._fetch_detail_source_tags(article_id)
        return IngestedItem(
            source_id=self.source_id,
            title=clean_title,
            source_url=canonical_url,
            canonical_url=canonical_url,
            published_at=published_dt.isoformat(),
            summary=self.clean_text(summary),
            byline=self.clean_text(byline),
            section="",
            discovery_method="cls_homepage_next_data",
            rank_position=rank_position,
            rank_section=section_name,
            source_tags=source_tags,
        )

    def _normalize_epoch(self, value: int | str | None) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            epoch = int(value)
        except (TypeError, ValueError):
            return None
        if epoch > 10_000_000_000:
            epoch = epoch // 1000
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    def _extract_source_tags(self, entry: dict) -> list[str]:
        tags: list[str] = []
        for subject in entry.get("subjects") or entry.get("subject") or []:
            if not isinstance(subject, dict):
                continue
            name = subject.get("subject_name") or subject.get("name")
            self._append_tag(tags, name)
        for tag in entry.get("tags") or entry.get("visibleTags") or []:
            if not isinstance(tag, dict):
                continue
            self._append_tag(tags, tag.get("name"))
        return tags

    def _fetch_detail_source_tags(self, article_id: int | str) -> list[str]:
        try:
            html = self.request_text(f"https://www.cls.cn/detail/{article_id}", timeout=10)
        except Exception:
            return []
        try:
            state = self._extract_next_data(html)
        except Exception:
            return []
        detail = state.get("props", {}).get("pageProps", {}).get("articleDetail", {})
        return self._extract_source_tags(detail)

    def _append_tag(self, tags: list[str], raw_value: object) -> None:
        tag = self.clean_text(str(raw_value or ""))
        if not tag or tag in self.ignored_source_tags or tag in tags:
            return
        tags.append(tag)
