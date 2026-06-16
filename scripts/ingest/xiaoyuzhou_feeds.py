#!/usr/bin/env python3
"""Xiaoyuzhou podcast RSS adapter for configured feeds."""

from __future__ import annotations

from datetime import datetime
import os
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


class XiaoyuzhouFeedsAdapter(BaseAdapter):
    source_id = "xiaoyuzhou-feeds"

    def fetch(self) -> list[IngestedItem]:
        feed_urls = [u.strip() for u in os.environ.get("XIAOYUZHOU_FEED_URLS", "").split(",") if u.strip()]
        collected: list[IngestedItem] = []
        for feed_url in feed_urls[:50]:
            collected.extend(self._fetch_feed(feed_url))
        return dedupe_items(collected)

    def _fetch_feed(self, feed_url: str) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(feed_url)
        except Exception:
            return []
        root = ET.fromstring(xml_text)
        channel_title = self.clean_text(root.findtext("./channel/title", default=""))
        items: list[IngestedItem] = []
        for node in root.findall("./channel/item")[:40]:
            title = self.clean_text(node.findtext("title", default=""))
            link = self.clean_text(node.findtext("link", default=""))
            pub_date = self.clean_text(node.findtext("pubDate", default=""))
            description = self.clean_text(node.findtext("description", default=""))
            if not title or not link or not pub_date:
                continue
            try:
                published_at = self.normalize_published_at(pub_date)
            except Exception:
                continue
            if not self.within_lookback(datetime.fromisoformat(published_at)):
                continue
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=link,
                    canonical_url=link,
                    published_at=published_at,
                    summary=description[:320],
                    byline=channel_title,
                    section="podcast_episode",
                    discovery_method="xiaoyuzhou_or_podcast_rss",
                    body_text=description,
                    fulltext_status="full_text_capable" if description else "partial_only",
                    fulltext_note="episode_description_only_transcript_not_fetched",
                )
            )
        return items
