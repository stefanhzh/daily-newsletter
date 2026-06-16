#!/usr/bin/env python3
"""TikTok public profile signal adapter.

TikTok is intentionally handled as a weak signal source here. Public pages are
dynamic and often hide stable video metadata from lightweight HTTP fetches, so
this adapter does not pretend to be a reliable full-content extractor.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from urllib.parse import quote

from .base import BaseAdapter, IngestedItem, dedupe_items


class TikTokProfileSignalsAdapter(BaseAdapter):
    source_id = "tiktok-profile-signals"

    def fetch(self) -> list[IngestedItem]:
        handles = [
            h.strip().lstrip("@")
            for h in os.environ.get("TIKTOK_HANDLES", "openai,tiktok").split(",")
            if h.strip()
        ]
        collected: list[IngestedItem] = []
        for handle in handles[:20]:
            collected.extend(self._fetch_handle(handle))
        return dedupe_items(collected)

    def _fetch_handle(self, handle: str) -> list[IngestedItem]:
        profile_url = f"https://www.tiktok.com/@{handle}"
        mirror_url = f"https://r.jina.ai/http://www.tiktok.com/@{quote(handle)}"
        try:
            text = self.request_text(mirror_url, timeout=30)
        except Exception:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        items: list[IngestedItem] = []
        for idx, match in enumerate(
            re.finditer(r"\[([^\]]{12,240})\]\((https://www\.tiktok\.com/@[^)]+/video/\d+)[^)]*\)", text),
            start=1,
        ):
            body = self.clean_text(match.group(1))
            url = match.group(2)
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=body[:120],
                    source_url=url,
                    canonical_url=url,
                    published_at=now_iso,
                    summary=body[:400],
                    byline=f"@{handle}",
                    section="profile_videos",
                    discovery_method="r_jina_tiktok_profile_markdown",
                    body_text=body,
                    fulltext_status="metadata_only",
                    fulltext_note="public_profile_mirror_may_omit_video_body_and_precise_publish_time",
                    rank_position=idx,
                    rank_section=f"TikTok profile: @{handle}",
                )
            )
            if len(items) >= 10:
                break
        if items:
            return items

        lines = [self.clean_text(line) for line in text.splitlines()]
        lines = [line for line in lines if line and not line.startswith(("![", "[![", "http"))]
        useful = []
        for line in lines:
            if re.search(r"(followers|following|likes|posts|videos?)", line, re.IGNORECASE):
                useful.append(line)
            elif handle.lower() in line.lower() and len(line) <= 180:
                useful.append(line)
        snapshot = self.clean_text(" | ".join(dict.fromkeys(useful[:12])))
        if not snapshot:
            return []

        return [
            IngestedItem(
                source_id=self.source_id,
                title=f"TikTok @{handle} profile signal",
                source_url=profile_url,
                canonical_url=profile_url,
                published_at=now_iso,
                summary=snapshot[:500],
                byline=f"@{handle}",
                section="profile_signal",
                discovery_method="r_jina_tiktok_profile_markdown",
                body_text=snapshot,
                fulltext_status="metadata_only",
                fulltext_note="profile_level_signal_only; reliable video search needs official API, authenticated session, or third-party browser infrastructure",
                rank_position=1,
                rank_section=f"TikTok profile: @{handle}",
            )
        ]
