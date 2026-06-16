from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from localization import clean_text, localize_text, polish_observation_summary, zh


TECH_DYNAMICS_TITLE = zh(r"\u6280\u672f\u52a8\u6001")
TECH_DYNAMICS_NOTE = zh(
    r"\u53c2\u8003 DailyBrief \u7684\u6280\u672f\u52a8\u6001\u677f\u5757\uff1a"
    r"\u4fdd\u7559\u6280\u672f\u6e90\u7684\u539f\u751f\u70ed\u5ea6\u548c\u65f6\u95f4\u987a\u5e8f\uff0c"
    r"\u4f7f\u7528\u4e2d\u6587\u6807\u9898\u548c\u4e2d\u6587\u6458\u8981\u63d0\u9ad8\u53ef\u8bfb\u6027\u3002"
)
OPEN_SOURCE_LABEL = zh(r"\u5f00\u6e90\u9879\u76ee\u70ed\u699c")
ISSUES_LABEL = zh(r"\u5f00\u53d1\u8005\u95ee\u9898\u70ed\u5ea6")
AI_OFFICIAL_LABEL = zh(r"AI \u5b98\u65b9\u4e0e\u6a21\u578b\u52a8\u6001")
TECH_MEDIA_LABEL = zh(r"\u6280\u672f\u5a92\u4f53\u4e0e\u793e\u533a")
TREND_SIGNALS_LABEL = zh(r"\u641c\u7d22\u4e0e\u5e73\u53f0\u4fe1\u53f7")
ITEMS_UNIT = zh(r"\u6761")
ZH_TITLE_LABEL = zh(r"\u4e2d\u6587\u6807\u9898")
ZH_SUMMARY_LABEL = zh(r"\u4e2d\u6587\u6458\u8981")
SOURCE_LABEL = zh(r"\u6765\u6e90")
RANK_LABEL = zh(r"\u6392\u540d")
PROJECT_DESC_LABEL = zh(r"\u9879\u76ee\u7b80\u4ecb")
LANGUAGE_LABEL = zh(r"\u6280\u672f\u6808")
TOTAL_STARS_LABEL = zh(r"\u603b\u661f\u6807")
STARS_TODAY_LABEL = zh(r"\u4eca\u65e5\u65b0\u589e")


TECH_SOURCE_LABELS = {
    "github-trending": "GitHub Trending",
    "github-issues-trends": "GitHub Issues Trends",
    "openai-blog": "OpenAI Blog",
    "anthropic-news": "Anthropic News",
    "huggingface": "Hugging Face",
    "latent-space": "Latent Space",
    "techcrunch": "TechCrunch",
    "semianalysis": "SemiAnalysis",
    "stratechery": "Stratechery",
    "a16z-blog": "a16z Blog",
    "y-combinator": "Y Combinator",
    "lesswrong": "LessWrong",
    "lobsters": "Lobsters",
    "google-trends": "Google Trends",
    "bilibili-popular": "Bilibili Popular",
    "zhihu-hot": "Zhihu Hot",
    "youtube-channel-feeds": "YouTube Channel Feeds",
}


TECH_GROUPS = [
    {
        "id": "open-source",
        "label": OPEN_SOURCE_LABEL,
        "source_ids": {"github-trending"},
        "preserve_rank": True,
        "limit": 8,
    },
    {
        "id": "developer-issues",
        "label": ISSUES_LABEL,
        "source_ids": {"github-issues-trends"},
        "preserve_rank": True,
        "limit": 8,
    },
    {
        "id": "ai-official",
        "label": AI_OFFICIAL_LABEL,
        "source_ids": {"openai-blog", "anthropic-news", "huggingface", "latent-space"},
        "preserve_rank": False,
        "limit": 10,
    },
    {
        "id": "tech-media-community",
        "label": TECH_MEDIA_LABEL,
        "source_ids": {
            "techcrunch",
            "semianalysis",
            "stratechery",
            "a16z-blog",
            "y-combinator",
            "lesswrong",
            "lobsters",
        },
        "preserve_rank": False,
        "limit": 10,
    },
    {
        "id": "trend-signals",
        "label": TREND_SIGNALS_LABEL,
        "source_ids": {"google-trends", "bilibili-popular", "zhihu-hot", "youtube-channel-feeds"},
        "preserve_rank": True,
        "limit": 8,
    },
]


def resolve_raw_items_path(payload: dict[str, Any], root: Path) -> Path | None:
    raw_path = clean_text((payload.get("run_meta") or {}).get("input"))
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    return path if path.exists() else None


def build_tech_dynamics(raw_items: list[dict[str, Any]], *, per_group: int | None = None) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group in TECH_GROUPS:
        source_ids = group["source_ids"]
        items = [
            normalize_tech_item(item)
            for item in raw_items
            if clean_text(item.get("source_id")) in source_ids
        ]
        items = [item for item in items if item["title"] and item["url"]]
        items.sort(key=lambda item: tech_sort_key(item, preserve_rank=bool(group["preserve_rank"])))
        limit = per_group or int(group["limit"])
        groups.append(
            {
                "id": group["id"],
                "label": group["label"],
                "items": items[:limit],
                "total": len(items),
            }
        )
    return [group for group in groups if group["items"]]


def normalize_tech_item(item: dict[str, Any]) -> dict[str, Any]:
    source_id = clean_text(item.get("source_id"))
    summary = clean_text(item.get("summary") or item.get("body_text"))
    github_meta = parse_github_trending_summary(summary) if source_id == "github-trending" else {}
    return {
        "source_id": source_id,
        "source_name": TECH_SOURCE_LABELS.get(source_id, source_id),
        "title": clean_text(item.get("title")),
        "url": clean_text(item.get("canonical_url") or item.get("source_url") or item.get("url")),
        "summary": summary,
        "description": github_meta.get("description", ""),
        "language": github_meta.get("language", ""),
        "total_stars": github_meta.get("total_stars", ""),
        "stars_today": github_meta.get("stars_today", ""),
        "published_at": clean_text(item.get("published_at")),
        "rank_position": parse_rank(item.get("rank_position")),
        "rank_section": clean_text(item.get("rank_section") or item.get("section")),
        "byline": clean_text(item.get("byline")),
        "discovery_method": clean_text(item.get("discovery_method")),
    }


def tech_sort_key(item: dict[str, Any], *, preserve_rank: bool) -> tuple[Any, ...]:
    rank = item.get("rank_position")
    if preserve_rank and isinstance(rank, int) and rank > 0:
        return (0, rank, item["title"])
    return (1, -timestamp(item.get("published_at")), item["title"])


def parse_rank(value: Any) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def timestamp(value: Any) -> float:
    text = clean_text(value)
    if not text:
        return 0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def translation_targets(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for group in groups:
        for item in group["items"]:
            targets.append(
                {
                    "primary_title": item["title"],
                    "summary": item.get("description") or item["summary"],
                    "related_reports": [],
                }
            )
    return targets


def item_title_zh(item: dict[str, Any], translations: dict[str, str]) -> str:
    if item.get("source_id") == "github-trending":
        return ""
    return localize_text(item.get("title"), translations)


def item_summary_zh(item: dict[str, Any], translations: dict[str, str]) -> str:
    if item.get("source_id") == "github-trending":
        return github_trending_summary_zh(item, translations)
    summary = localize_text(item.get("summary"), translations)
    if not summary:
        summary = item_title_zh(item, translations)
    return polish_observation_summary(summary)


def parse_github_trending_summary(summary: str) -> dict[str, str]:
    parts = [clean_text(part) for part in summary.split("|") if clean_text(part)]
    description = parts[0] if parts else ""
    language = ""
    total_stars = ""
    stars_today = ""
    for part in parts[1:]:
        lower = part.lower()
        if lower.startswith("total stars:"):
            total_stars = clean_text(part.split(":", 1)[1])
            continue
        if "stars today" in lower:
            match = re.search(r"([\d,]+)\s+stars?\s+today", part, re.I)
            stars_today = match.group(1) if match else part
            continue
        if not language and re.fullmatch(r"[A-Za-z0-9+#.\- ]{1,30}", part):
            language = part
    return {
        "description": description,
        "language": language,
        "total_stars": total_stars,
        "stars_today": stars_today,
    }


def github_trending_summary_zh(item: dict[str, Any], translations: dict[str, str]) -> str:
    description = clean_text(item.get("description"))
    description_zh = localize_text(description, translations) if description else ""
    if not description_zh:
        description_zh = description
    parts = []
    if description_zh:
        parts.append(f"{PROJECT_DESC_LABEL}：{description_zh}")
    if item.get("language"):
        parts.append(f"{LANGUAGE_LABEL}：{item['language']}")
    if item.get("total_stars"):
        parts.append(f"{TOTAL_STARS_LABEL}：{item['total_stars']}")
    if item.get("stars_today"):
        parts.append(f"{STARS_TODAY_LABEL}：{item['stars_today']} stars")
    return polish_observation_summary("；".join(parts))
