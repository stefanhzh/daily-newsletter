#!/usr/bin/env python3
"""Bilibili popular video adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from .base import BaseAdapter, IngestedItem, dedupe_items


class BilibiliPopularAdapter(BaseAdapter):
    source_id = "bilibili-popular"
    api_url = "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1"

    def fetch(self) -> list[IngestedItem]:
        try:
            payload = json.loads(self.request_text(self.api_url))
        except Exception:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        collected: list[IngestedItem] = []
        for rank, raw in enumerate(payload.get("data", {}).get("list", []), start=1):
            bvid = raw.get("bvid") or ""
            title = self.clean_text(raw.get("title") or "")
            if not bvid or not title:
                continue
            url = f"https://www.bilibili.com/video/{bvid}"
            stats = raw.get("stat") or {}
            summary = self.clean_text(raw.get("desc") or "")
            metric_bits = [
                f"views={stats.get('view', 0)}",
                f"likes={stats.get('like', 0)}",
                f"coins={stats.get('coin', 0)}",
                f"favorites={stats.get('favorite', 0)}",
            ]
            collected.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=url,
                    canonical_url=url,
                    published_at=now_iso,
                    summary=f"{summary[:260]} | {'; '.join(metric_bits)}",
                    byline=self.clean_text(raw.get("owner", {}).get("name") or ""),
                    section=raw.get("tname") or "popular",
                    discovery_method="bilibili_popular_api",
                    body_text=summary,
                    fulltext_status="full_text_capable" if summary else "partial_only",
                    fulltext_note="video_description_and_metrics_only",
                    rank_position=rank,
                    rank_section="Bilibili Popular",
                )
            )
        return dedupe_items(collected)
