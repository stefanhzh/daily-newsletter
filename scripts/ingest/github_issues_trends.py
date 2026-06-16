#!/usr/bin/env python3
"""GitHub Issues trends ingestion adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from .base import BaseAdapter, IngestedItem, dedupe_items


class GitHubIssuesTrendsAdapter(BaseAdapter):
    source_id = "github-issues-trends"
    rank_section = "Global GitHub Issues Trends (7d)"
    max_per_repo = 1
    skip_title_fragments = (
        "運用ループ",
        "operation loop",
    )
    skip_labels = {
        "daily-operation",
        "automation",
    }

    def fetch(self) -> list[IngestedItem]:
        api_url = self._build_search_url()
        try:
            payload = self._request_json(api_url)
        except Exception:
            return []

        items = payload.get("items") or []
        collected: list[IngestedItem] = []
        repo_counts: dict[str, int] = {}
        rank_position = 0
        for node in items:
            item = self._node_to_item(node, api_url)
            if item is not None:
                repo_key = item.byline or "GitHub Issues"
                if repo_counts.get(repo_key, 0) >= self.max_per_repo:
                    continue
                rank_position += 1
                item.rank_position = rank_position
                repo_counts[repo_key] = repo_counts.get(repo_key, 0) + 1
                collected.append(item)
        return dedupe_items(collected)

    def _build_search_url(self) -> str:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        query = f"is:issue archived:false created:>={since}"
        return (
            "https://api.github.com/search/issues"
            f"?q={quote(query)}&sort=comments&order=desc&per_page=30"
        )

    def _request_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def _node_to_item(self, node: dict, source_url: str) -> IngestedItem | None:
        html_url = self.clean_text(node.get("html_url", ""))
        title = self.clean_text(node.get("title", ""))
        updated_at = self.clean_text(node.get("updated_at", ""))
        if not html_url or not title or not updated_at:
            return None
        title_lower = title.lower()
        if any(fragment.lower() in title_lower for fragment in self.skip_title_fragments):
            return None

        repository_url = self.clean_text(node.get("repository_url", ""))
        repo_name = repository_url.replace("https://api.github.com/repos/", "") if repository_url else ""
        comments = int(node.get("comments") or 0)
        state = self.clean_text(node.get("state", ""))
        labels = [self.clean_text(label.get("name", "")) for label in node.get("labels") or []]
        labels = [label for label in labels if label]
        if any(label.lower() in self.skip_labels for label in labels):
            return None
        body = self.clean_text(node.get("body", ""))

        summary_parts = []
        if repo_name:
            summary_parts.append(f"Repo: {repo_name}")
        if comments:
            summary_parts.append(f"Comments: {comments}")
        if state:
            summary_parts.append(f"State: {state}")
        if labels:
            summary_parts.append(f"Labels: {', '.join(labels[:4])}")
        if body:
            excerpt = body[:240].rstrip()
            if len(body) > 240:
                excerpt += "..."
            summary_parts.append(excerpt)
        summary = " | ".join(summary_parts)

        return IngestedItem(
            source_id=self.source_id,
            title=title,
            source_url=source_url,
            canonical_url=html_url,
            published_at=updated_at,
            summary=summary,
            byline=repo_name or "GitHub Issues",
            section="issues_trends",
            discovery_method="github_search_issues_api",
            body_text="",
            fulltext_status="partial_only",
            fulltext_note="ranking_surface_no_native_full_thread_body",
            rank_position=0,
            rank_section=self.rank_section,
        )
