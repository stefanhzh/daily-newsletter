#!/usr/bin/env python3
"""Gelonghui ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from bs4 import BeautifulSoup

from .base import BaseAdapter, IngestedItem, dedupe_items


class GelonghuiAdapter(BaseAdapter):
    source_id = "gelonghui"
    news_url = "https://www.gelonghui.com/news"

    def fetch(self) -> list[IngestedItem]:
        try:
            html = self.request_text(self.news_url)
        except Exception:
            return []

        items: list[IngestedItem] = []
        links, rank_section = self._extract_ranked_links(html)
        for rank, (url, title) in enumerate(links[:40], start=1):
            try:
                item = self._fetch_article(url, title, rank_position=rank, rank_section=rank_section)
            except Exception:
                continue
            if item is not None:
                items.append(item)
        return dedupe_items(items)

    def _extract_ranked_links(self, html: str) -> tuple[list[tuple[str, str]], str]:
        hot_links = self._extract_listing_links(html, "section.hotArticle ul.active a[href^='/p/']")
        if hot_links:
            return hot_links, "hot_article_recommended"
        return self._extract_listing_links(html, "section.news-container-right a[href^='/p/']"), "page_body_fallback"

    def _extract_listing_links(self, html: str, selector: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select(selector):
            href = (anchor.get("href") or "").strip()
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not href or not title or href in seen:
                continue
            seen.add(href)
            links.append((f"https://www.gelonghui.com{href}", title))
        return links

    def _fetch_article(
        self,
        url: str,
        title_hint: str,
        *,
        rank_position: int,
        rank_section: str,
    ) -> IngestedItem | None:
        html = self.request_text(url)
        created = self._extract_epoch_field(html, "createTimestamp")
        if created is None:
            created = self._extract_epoch_field(html, "updateTimestamp")
        if created is None:
            return None

        published_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        if not self.within_lookback(published_dt):
            return None

        title = self._extract_page_title(html) or title_hint
        summary = self._extract_meta_description(html)
        body_text = self._extract_article_paragraphs(html)
        source_tags = self._extract_source_tags(html)

        return IngestedItem(
            source_id=self.source_id,
            title=self.clean_text(title),
            source_url=url,
            canonical_url=url,
            published_at=published_dt.isoformat(),
            summary=self.clean_text(summary)[:320],
            byline="Gelonghui",
            section="",
            discovery_method="gelonghui_hot_article_listing",
            body_text=body_text,
            fulltext_note="article_dom_paragraphs",
            rank_position=rank_position,
            rank_section=rank_section,
            source_tags=source_tags,
        )

    def _extract_epoch_field(self, html: str, field_name: str) -> int | None:
        match = re.search(rf"{re.escape(field_name)}:(\d{{10}})", html)
        return int(match.group(1)) if match else None

    def _extract_page_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if "-" in title:
            title = title.split("-", 1)[0].strip()
        return title

    def _extract_meta_description(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        node = soup.find("meta", attrs={"name": "description"})
        if node and node.get("content"):
            return self.clean_text(self._repair_mojibake(node["content"]))
        return ""

    def _repair_mojibake(self, value: str) -> str:
        text = value or ""
        for encoding in ("utf-8", "gbk"):
            try:
                repaired = text.encode("latin1").decode(encoding)
            except Exception:
                continue
            if self._contains_cjk(repaired):
                return repaired
        return text

    def _contains_cjk(self, value: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in value)

    def _extract_source_tags(self, html: str) -> list[str]:
        tags: list[str] = []
        nuxt_script = self._extract_nuxt_script(html)
        if not nuxt_script:
            return tags

        related_infos = self._extract_inline_array_names(nuxt_script, "relatedInfos")
        related_stocks = self._extract_referenced_array_names(nuxt_script, "relatedStocks")
        for value in [*related_infos, *related_stocks]:
            self._append_tag(tags, value)
        return tags[:8]

    def _extract_nuxt_script(self, html: str) -> str:
        match = re.search(r"<script>window\.__NUXT__=(.*?)</script>", html, re.S)
        return match.group(1) if match else ""

    def _extract_inline_array_names(self, script: str, field_name: str) -> list[str]:
        array_text = self._extract_inline_array_text(script, field_name)
        if not array_text:
            return []
        return self._extract_name_values(array_text)

    def _extract_inline_array_text(self, script: str, field_name: str) -> str:
        marker = f"{field_name}:["
        start = script.find(marker)
        if start == -1:
            return ""

        pos = start + len(marker) - 1
        depth = 0
        in_string = False
        escaped = False
        for index in range(pos, len(script)):
            char = script[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return script[pos : index + 1]
        return ""

    def _extract_referenced_array_names(self, script: str, field_name: str) -> list[str]:
        inline_names = self._extract_inline_array_names(script, field_name)
        if inline_names:
            return inline_names

        match = re.search(rf"{re.escape(field_name)}:([A-Za-z_$][A-Za-z0-9_$]*)", script)
        if not match:
            return []

        variable_name = match.group(1)
        assignment_pattern = re.compile(
            rf"{re.escape(variable_name)}\[\d+\]=\{{(.*?)\}};",
            re.S,
        )
        names: list[str] = []
        for assignment in assignment_pattern.finditer(script):
            names.extend(self._extract_name_values(assignment.group(1)))
        return names

    def _extract_name_values(self, text: str) -> list[str]:
        names: list[str] = []
        for match in re.finditer(r'name:"((?:\\.|[^"])*)"', text):
            decoded = self._decode_js_string(match.group(1))
            if decoded:
                names.append(decoded)
        return names

    def _decode_js_string(self, value: str) -> str:
        try:
            return json.loads(f'"{value}"')
        except Exception:
            return value

    def _append_tag(self, tags: list[str], value: str) -> None:
        cleaned = self.clean_text(self._repair_mojibake(value))
        if cleaned and cleaned not in {"原创"} and cleaned not in tags:
            tags.append(cleaned)

    def _extract_article_paragraphs(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        paragraphs: list[str] = []
        for node in soup.select("article p"):
            text = self.clean_text(node.get_text(" ", strip=True))
            if len(text) >= 20:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)
