#!/usr/bin/env python3
"""Reddit hot posts adapter.

Requires REDDIT_BEARER_TOKEN for the official OAuth API in many environments.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from urllib.request import Request, urlopen

from .base import BaseAdapter, IngestedItem, dedupe_items


class RedditHotAdapter(BaseAdapter):
    source_id = "reddit-hot"

    def fetch(self) -> list[IngestedItem]:
        token = os.environ.get("REDDIT_BEARER_TOKEN")
        if not token:
            return []
        subreddit = os.environ.get("REDDIT_SUBREDDIT", "all").strip("/") or "all"
        url = f"https://oauth.reddit.com/r/{subreddit}/hot?limit=50"
        headers = {
            "User-Agent": "daily-newsletter/0.1 by local-user",
            "Authorization": f"Bearer {token}",
        }
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        collected: list[IngestedItem] = []
        for rank, child in enumerate(payload.get("data", {}).get("children", []), start=1):
            data = child.get("data") or {}
            title = self.clean_text(data.get("title") or "")
            permalink = data.get("permalink") or ""
            if not title or not permalink:
                continue
            reddit_url = f"https://www.reddit.com{permalink}"
            outbound_url = data.get("url") or reddit_url
            summary = self.clean_text(data.get("selftext") or data.get("link_flair_text") or "")
            collected.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=reddit_url,
                    canonical_url=reddit_url,
                    published_at=now_iso,
                    summary=f"{summary[:240]} | score={data.get('score', 0)}; comments={data.get('num_comments', 0)}; outbound={outbound_url}",
                    byline=f"u/{data.get('author', '')}",
                    section=f"r/{data.get('subreddit', subreddit)}",
                    discovery_method="reddit_oauth_hot_api",
                    body_text=summary,
                    fulltext_status="full_text_capable" if summary else "partial_only",
                    fulltext_note="reddit_post_body_or_link_metadata",
                    rank_position=rank,
                    rank_section=f"Reddit r/{subreddit} Hot",
                )
            )
        return dedupe_items(collected)
