#!/usr/bin/env python3
"""Zhihu hot-list adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from urllib.request import Request, urlopen

from .auth_state import cookie_header_from_storage_state
from .base import BaseAdapter, IngestedItem, dedupe_items


class ZhihuHotAdapter(BaseAdapter):
    source_id = "zhihu-hot"
    api_url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"

    def fetch(self) -> list[IngestedItem]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.zhihu.com/hot",
            "X-Requested-With": "fetch",
        }
        cookie = os.environ.get("ZHIHU_COOKIE") or cookie_header_from_storage_state(
            self.source_id,
            ["zhihu.com"],
        )
        if cookie:
            headers["Cookie"] = cookie

        try:
            request = Request(self.api_url, headers=headers)
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        collected: list[IngestedItem] = []
        for rank, entry in enumerate(payload.get("data", []), start=1):
            target = entry.get("target") or {}
            qid = target.get("id")
            title = self.clean_text(target.get("title") or "")
            if not qid or not title:
                continue
            url = f"https://www.zhihu.com/question/{qid}"
            summary = self.clean_text(target.get("excerpt") or "")
            collected.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=url,
                    canonical_url=url,
                    published_at=now_iso,
                    summary=(
                        f"{summary[:260]} | followers={target.get('follower_count', 0)}; "
                        f"answers={target.get('answer_count', 0)}"
                    ),
                    byline="Zhihu Hot",
                    section="hot",
                    discovery_method="zhihu_hot_api",
                    body_text=summary,
                    fulltext_status="partial_only",
                    fulltext_note="hotlist_question_excerpt_only",
                    rank_position=rank,
                    rank_section="Zhihu Hot",
                )
            )
        return dedupe_items(collected)
