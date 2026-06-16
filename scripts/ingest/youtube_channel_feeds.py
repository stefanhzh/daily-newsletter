#!/usr/bin/env python3
"""YouTube channel RSS adapter."""

from __future__ import annotations

from datetime import datetime
import os
import re
import xml.etree.ElementTree as ET

from .base import BaseAdapter, IngestedItem, dedupe_items


class YouTubeChannelFeedsAdapter(BaseAdapter):
    source_id = "youtube-channel-feeds"

    def fetch(self) -> list[IngestedItem]:
        feed_urls = [u.strip() for u in os.environ.get("YOUTUBE_FEED_URLS", "").split(",") if u.strip()]
        channel_ids = [c.strip() for c in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",") if c.strip()]
        handles = [
            h.strip().lstrip("@")
            for h in os.environ.get("YOUTUBE_HANDLES", "OpenAI,AnthropicAI").split(",")
            if h.strip()
        ]
        collected: list[IngestedItem] = []
        for handle in handles[:20]:
            channel_id = self._resolve_handle(handle)
            if channel_id:
                channel_ids.append(channel_id)
            collected.extend(self._fetch_handle_mirror(handle))
        feed_urls.extend(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            for channel_id in channel_ids
        )
        for feed_url in feed_urls[:50]:
            collected.extend(self._fetch_feed(feed_url))
        return dedupe_items(collected)

    def _fetch_handle_mirror(self, handle: str) -> list[IngestedItem]:
        try:
            text = self.request_text(f"https://r.jina.ai/http://www.youtube.com/@{handle}/videos", timeout=30)
        except Exception:
            return []
        now = datetime.now().astimezone().isoformat()
        items: list[IngestedItem] = []
        seen: set[str] = set()
        for match in re.finditer(r"\[([^\]]{8,180})\]\((https?://www\.youtube\.com/watch\?v=[^)]+)\)", text):
            title = self.clean_text(match.group(1))
            link = match.group(2)
            if not title or link in seen or title.lower().startswith("image "):
                continue
            seen.add(link)
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=link,
                    canonical_url=link,
                    published_at=now,
                    summary=f"Channel handle: @{handle}",
                    byline=f"@{handle}",
                    section="channel_uploads",
                    discovery_method="r_jina_youtube_handle_markdown",
                    fulltext_status="partial_only",
                    fulltext_note="video_title_link_only_transcript_not_fetched",
                )
            )
            if len(items) >= 10:
                break
        return items

    def _resolve_handle(self, handle: str) -> str:
        try:
            html = self.request_text(f"https://www.youtube.com/@{handle}", timeout=20)
        except Exception:
            return ""
        match = re.search(r'"externalId":"([^"]+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'<link rel="canonical" href="https://www.youtube.com/channel/([^"]+)"', html)
        return match.group(1) if match else ""

    def _fetch_feed(self, feed_url: str) -> list[IngestedItem]:
        try:
            xml_text = self.request_text(feed_url)
        except Exception:
            return []
        root = ET.fromstring(xml_text)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        author = root.findtext("atom:author/atom:name", default="", namespaces=ns)
        items: list[IngestedItem] = []
        for entry in root.findall("atom:entry", ns)[:30]:
            title = self.clean_text(entry.findtext("atom:title", default="", namespaces=ns))
            link_node = entry.find("atom:link", ns)
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            published_raw = entry.findtext("atom:published", default="", namespaces=ns)
            summary = self.clean_text(entry.findtext("media:group/media:description", default="", namespaces=ns))
            if not title or not link or not published_raw:
                continue
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00")).isoformat()
            if not self.within_lookback(datetime.fromisoformat(published_at)):
                continue
            items.append(
                IngestedItem(
                    source_id=self.source_id,
                    title=title,
                    source_url=link,
                    canonical_url=link,
                    published_at=published_at,
                    summary=summary[:320],
                    byline=author,
                    section="channel_uploads",
                    discovery_method="youtube_channel_rss",
                    body_text=summary,
                    fulltext_status="full_text_capable" if summary else "partial_only",
                    fulltext_note="video_description_only_transcript_not_fetched",
                )
            )
        return items
