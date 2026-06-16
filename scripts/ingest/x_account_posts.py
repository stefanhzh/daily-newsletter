#!/usr/bin/env python3
"""X account posts adapter using lightweight text mirrors."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from urllib.parse import quote

from .base import BaseAdapter, IngestedItem, dedupe_items


class XAccountPostsAdapter(BaseAdapter):
    source_id = "x-account-posts"

    def fetch(self) -> list[IngestedItem]:
        handles = [
            h.strip().lstrip("@")
            for h in os.environ.get("X_ACCOUNT_HANDLES", "OpenAI,AnthropicAI,sama").split(",")
            if h.strip()
        ]
        collected: list[IngestedItem] = []
        for handle in handles[:20]:
            collected.extend(self._fetch_handle(handle))
        return dedupe_items(collected)

    def _fetch_handle(self, handle: str) -> list[IngestedItem]:
        url = f"https://r.jina.ai/http://x.com/{quote(handle)}"
        try:
            text = self.request_text(url, timeout=30)
        except Exception:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        posts: list[IngestedItem] = []
        for match in re.finditer(r"\[([^\]]{20,280})\]\(https://x\.com/[^/]+/status/(\d+)\)", text):
            body = self.clean_text(match.group(1))
            status_id = match.group(2)
            if not body or body.lower().startswith("image "):
                continue
            canonical_url = f"https://x.com/{handle}/status/{status_id}"
            posts.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=body[:120],
                    source_url=canonical_url,
                    canonical_url=canonical_url,
                    published_at=now_iso,
                    summary=body[:400],
                    byline=f"@{handle}",
                    section="account_posts",
                    discovery_method="r_jina_x_profile_markdown",
                    body_text=body,
                    fulltext_status="full_text_capable",
                    fulltext_note="short_post_body_from_public_profile_mirror",
                )
            )
            if len(posts) >= 10:
                break
        if posts:
            return posts

        # r.jina.ai often renders profile timelines as plain text without
        # preserving status URLs. Keep these as profile-level discovery signals.
        section = text.split("##", 1)[-1] if "##" in text else text
        candidates: list[str] = []
        buffer: list[str] = []
        for raw_line in section.splitlines():
            line = self.clean_text(raw_line)
            if not line or line.startswith("![") or line.startswith("[![") or line.startswith("http"):
                continue
            if re.fullmatch(r"\d{1,2}:\d{2}", line):
                if buffer:
                    candidates.append(" ".join(buffer))
                    buffer = []
                continue
            if line in {handle, f"@{handle}", "Pinned"}:
                continue
            buffer.append(line)
            if len(" ".join(buffer)) > 180:
                candidates.append(" ".join(buffer))
                buffer = []
        if buffer:
            candidates.append(" ".join(buffer))

        profile_url = f"https://x.com/{handle}"
        for idx, body in enumerate(candidates[:10], start=1):
            body = self.clean_text(body)
            if len(body) < 30:
                continue
            posts.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=body[:120],
                    source_url=profile_url,
                    canonical_url=profile_url,
                    published_at=now_iso,
                    summary=body[:400],
                    byline=f"@{handle}",
                    section="account_posts",
                    discovery_method="r_jina_x_profile_markdown",
                    body_text=body,
                    fulltext_status="full_text_capable",
                    fulltext_note="profile_mirror_post_text_without_stable_status_url",
                    rank_position=idx,
                    rank_section=f"X profile: @{handle}",
                )
            )
        return posts
