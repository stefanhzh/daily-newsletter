#!/usr/bin/env python3
"""Shared ingestion primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import json
import re
from typing import Iterable
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)


@dataclass
class IngestedItem:
    source_id: str
    title: str
    source_url: str
    canonical_url: str
    published_at: str
    summary: str
    byline: str = ""
    section: str = ""
    discovery_method: str = ""
    body_text: str = ""
    fulltext_status: str = ""
    fulltext_note: str = ""
    rank_position: int = 0
    rank_section: str = ""
    source_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BaseAdapter:
    source_id = ""

    def __init__(self, *, lookback_hours: int = 24, user_agent: str = DEFAULT_USER_AGENT):
        self.lookback_hours = lookback_hours
        self.user_agent = user_agent

    def fetch(self) -> list[IngestedItem]:
        raise NotImplementedError

    def request_text(self, url: str, *, timeout: int = 20) -> str:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def within_lookback(self, published_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return published_at >= now - timedelta(hours=self.lookback_hours)

    def normalize_published_at(self, raw_value: str) -> str:
        parsed = parsedate_to_datetime(raw_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    def clean_text(self, value: str) -> str:
        compact = re.sub(r"\s+", " ", unescape(value or "")).strip()
        return compact


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for node in root.findall("./channel/item"):
        items.append(
            {
                "title": node.findtext("title", default=""),
                "link": node.findtext("link", default=""),
                "guid": node.findtext("guid", default=""),
                "pubDate": node.findtext("pubDate", default=""),
                "description": node.findtext("description", default=""),
            }
        )
    return items


def extract_meta_content(html: str, property_name: str) -> str:
    patterns = [
        rf'<meta[^>]+property="{re.escape(property_name)}"[^>]+content="([^"]+)"',
        rf"<meta[^>]+property='{re.escape(property_name)}'[^>]+content='([^']+)'",
        rf'<meta[^>]+name="{re.escape(property_name)}"[^>]+content="([^"]+)"',
        rf"<meta[^>]+name='{re.escape(property_name)}'[^>]+content='([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def dedupe_items(items: Iterable[IngestedItem]) -> list[IngestedItem]:
    seen: set[tuple[str, str]] = set()
    deduped: list[IngestedItem] = []
    for item in items:
        key = (item.title.strip().lower(), item.canonical_url or item.source_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def dump_items_to_json(items: Iterable[IngestedItem], output_path: str) -> None:
    payload = [item.to_dict() for item in items]
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def title_key(value: str) -> str:
    normalized = (value or "").lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", normalized)
    return normalized.strip()
