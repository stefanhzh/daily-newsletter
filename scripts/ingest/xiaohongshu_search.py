#!/usr/bin/env python3
"""Xiaohongshu keyword search adapter using Playwright XHR interception."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from urllib.parse import quote

from .auth_state import playwright_storage_state
from .base import BaseAdapter, IngestedItem, dedupe_items


class XiaohongshuSearchAdapter(BaseAdapter):
    source_id = "xiaohongshu-search"

    def fetch(self) -> list[IngestedItem]:
        keywords = [k.strip() for k in os.environ.get("XIAOHONGSHU_KEYWORDS", "").split(",") if k.strip()]
        if not keywords:
            return []
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return []

        collected: list[IngestedItem] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context_options = {
                    "user_agent": self.user_agent,
                    "locale": "zh-CN",
                    "timezone_id": "Asia/Shanghai",
                    "viewport": {"width": 1280, "height": 800},
                }
                storage_state = playwright_storage_state(self.source_id)
                if storage_state:
                    context_options["storage_state"] = storage_state
                context = browser.new_context(**context_options)
                for keyword in keywords[:8]:
                    collected.extend(self._search_keyword(context, keyword))
            finally:
                browser.close()
        return dedupe_items(collected)

    def _search_keyword(self, context, keyword: str) -> list[IngestedItem]:
        page = context.new_page()
        captured = {"payload": None}

        def on_response(response):
            try:
                if "/api/sns/web/v1/search/notes" in response.url and response.status == 200:
                    captured["payload"] = response.json()
            except Exception:
                return

        page.on("response", on_response)
        url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(6):
                if captured["payload"]:
                    break
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(1200)
        except Exception:
            pass
        finally:
            page.close()

        payload = captured["payload"]
        if not isinstance(payload, dict):
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        items: list[IngestedItem] = []
        for rank, raw in enumerate((payload.get("data") or {}).get("items") or [], start=1):
            note_card = raw.get("note_card") or {}
            note_id = raw.get("id") or note_card.get("note_id") or ""
            title = self.clean_text(note_card.get("display_title") or note_card.get("title") or "")
            desc = self.clean_text(note_card.get("desc") or "")
            if not note_id or not title:
                continue
            user = note_card.get("user") or {}
            interact = note_card.get("interact_info") or {}
            note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            summary = (
                f"{desc[:240]} | likes={interact.get('liked_count', 0)}; "
                f"collects={interact.get('collected_count', 0)}; "
                f"comments={interact.get('comment_count', 0)}"
            )
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=note_url,
                    canonical_url=note_url,
                    published_at=now_iso,
                    summary=summary,
                    byline=user.get("nickname") or user.get("nick_name") or "",
                    section="keyword_search",
                    discovery_method="xiaohongshu_search_xhr",
                    body_text=desc,
                    fulltext_status="full_text_capable" if desc else "partial_only",
                    fulltext_note="search_result_note_card_only_detail_page_not_fetched",
                    rank_position=rank,
                    rank_section=f"Xiaohongshu search: {keyword}",
                )
            )
        return items
