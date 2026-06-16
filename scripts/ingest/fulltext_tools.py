#!/usr/bin/env python3
"""Shared helpers for article full-text extraction and classification."""

from __future__ import annotations

from dataclasses import dataclass
import re
import json
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from .base import DEFAULT_USER_AGENT, IngestedItem, title_key


HEADERS = {"User-Agent": DEFAULT_USER_AGENT}
FULLTEXT_CHAR_THRESHOLD = 1200
FULLTEXT_PARAGRAPH_THRESHOLD = 5
REQUEST_TIMEOUT = 20
MIRROR_REQUEST_TIMEOUT = 30
MIRROR_ENABLED_SOURCES = {"wsj", "reuters"}
SYNDICATED_FULLTEXT_ENABLED_SOURCES = {"bloomberg"}
SYNDICATED_FULLTEXT_HOSTS: dict[str, list[str]] = {
    "bloomberg": ["msn.com"],
}
SYNDICATED_SEARCH_TIMEOUT = 15
SYNDICATED_FETCH_TIMEOUT = 25
SYNDICATED_TITLE_SIMILARITY_THRESHOLD = 0.52
SYNDICATED_CANDIDATE_LIMIT = 5


SOURCE_SELECTORS: dict[str, list[str]] = {
    "a16z-blog": [
        "article p",
        "main p",
        ".entry-content p",
        ".post-content p",
        "p",
    ],
    "reuters": [
        "[data-testid^='paragraph-']",
        "article p",
        "main p",
    ],
    "ap": [
        "div.RichTextStoryBody p",
        "article p",
        "main p",
    ],
    "cnbc": [
        "div.ArticleBody-articleBody p",
        "article p",
        "main p",
    ],
    "discord-blog": [
        "article p",
        "main p",
        ".w-richtext p",
        "p",
    ],
    "cailian": [
        "div.detail-content p",
        "div.article-content p",
        "article p",
        "main p",
    ],
    "caixin": [
        "div.r-content p",
        "div.c-content p",
        "div.c-content-box p",
        "div.common-main-content p",
        "div.article-content p",
        "div.content p",
        "article p",
        "main p",
    ],
    "yicai": [
        "div.multi-text.f-cb",
        "div.m-text div.multi-text",
        "div.m-articl-content p",
        "div.article-content p",
        "article p",
        "main p",
    ],
    "bloomberg": [
        "article p",
        "main p",
    ],
    "ft": [
        "article p",
        "main p",
    ],
    "wsj": [
        "article p",
        "main p",
    ],
    "huggingface": [
        "article p",
        "main p",
        "p",
    ],
    "bbc": [
        "[data-component='text-block'] p",
        "article p",
        "main p",
    ],
    "anthropic-news": [
        "main p",
        "article p",
        "p",
    ],
    "36kr": [
        "div.articleDetailContent p",
        "div.kr-rich-text-wrapper p",
        "article p",
        "main p",
    ],
    "openai-blog": [
        "main p",
        "article p",
    ],
    "techcrunch": [
        "div.entry-content p",
        "div.wp-block-post-content p",
        "main p",
        "article p",
    ],
    "telegram-blog": [
        "p",
    ],
    "ths-hotrank": [
        ".article-content p",
        ".main-content p",
        "article p",
        "main p",
    ],
    "nikkei-asia": [
        "main p",
        "article p",
    ],
    "politico": [
        "article p",
        "main p",
    ],
    "scmp": [
        "[data-qa*='Article'] p",
        "article p",
        "main p",
    ],
    "semafor": [
        "main p",
        "article p",
    ],
    "semianalysis": [
        "article p",
        "main p",
        "p",
    ],
    "stratechery": [
        "article p",
        "main p",
        "p",
    ],
    "y-combinator": [
        "article p",
        "main p",
        ".prose p",
    ],
    "lobsters": [
        "div.comment_text",
        "div.comment .comment_text",
        "div.story_text",
    ],
    "zerohedge": [
        "div.NodeStory_body p",
        "article p",
        "main p",
    ],
    "msn-bloomberg": [
        "article p",
        "main p",
        "[data-t*='article'] p",
        "p",
    ],
}


STRIP_SELECTORS = [
    "script",
    "style",
    "noscript",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
]


@dataclass
class FulltextResult:
    source_id: str
    title: str
    canonical_url: str
    http_status: int | None
    paragraphs: list[str]
    classification: str
    note: str

    @property
    def paragraph_count(self) -> int:
        return len(self.paragraphs)

    @property
    def body_chars(self) -> int:
        return sum(len(p) for p in self.paragraphs)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    replacements = {
        "拢": "£",
        "鈥?": "\"",
        "鈥": "\"",
        "銆": "",
        "锛": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _filter_source_paragraphs(source_id: str, paragraphs: list[str]) -> list[str]:
    if source_id == "wsj":
        blocked_patterns = [
            "Skip to Main Content",
            "What To Read Next",
            "Sections My Account",
            "Listen",
            "Subscribe Now",
            "Already a subscriber?",
            "Continue reading your article with",
            "a WSJ subscription",
            "Advertisement",
            "Reviews and recommendations, independent of The Wall Street Journal newsroom.",
            "Copyright ©",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            normalized = re.sub(r"\[[^\]]+\]\([^)]+\)", "", paragraph).strip()
            normalized = re.sub(r"^#+\s*", "", normalized).strip()
            if not normalized:
                continue
            if re.fullmatch(r"\d+", normalized):
                continue
            if re.fullmatch(r"(?:\*\s*){3,}", normalized):
                continue
            if normalized == "By":
                continue
            if re.fullmatch(r"\(\d+\s+min\)", normalized):
                continue
            if re.fullmatch(r"[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+(am|pm)\s+ET", normalized, re.IGNORECASE):
                continue
            if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}", normalized):
                continue
            if re.search(r"\.[A-Z][A-Z /&'.-]{6,}$", normalized):
                continue
            if any(pattern.lower() in normalized.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(normalized)
        return cleaned
    if source_id == "politico":
        blocked_patterns = [
            "View in browser",
            "Subscribe here",
            "Advertisement",
            "Presented by",
            "A message from",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "scmp":
        blocked_patterns = [
            "This article appeared in the South China Morning Post print edition",
            "Join ST’s Telegram channel",
            "Get more with myNEWS",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "bbc":
        blocked_patterns = [
            "Sign up for our Tech Decoded newsletter",
            "Outside the UK? Sign up here",
            "Get our flagship newsletter",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "nikkei-asia":
        blocked_patterns = [
            "To read the full story",
            "Subscribe",
            "Register now",
            "Unlock",
            "Continue reading",
            "Get in touch with our reporters",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "caixin":
        blocked_patterns = [
            "Unlock exclusive discounts",
            "Subscribe now",
            "We ve added you to our subscriber list",
            "We've added you to our subscriber list",
            "Copyright",
            "All Rights Reserved",
            "Get exposure for your startup",
            "Meet 5 of the best startups",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            paragraph = re.sub(r"^\d+\.\s*(?:\[para\.\s*\d+\s*\]\s*)+", "", paragraph).strip()
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "semafor":
        blocked_patterns = [
            "Sign up for Semafor",
            "Read it now",
            "Advertisement",
            "Most read",
            "Catch up on",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            normalized = (
                paragraph.replace("â\u0080\u0094", "—")
                .replace("â\u0080\u0099", "’")
                .replace("â\u0080\u009c", "“")
                .replace("â\u0080\u009d", "”")
            )
            if any(pattern.lower() in normalized.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(normalized)
        return cleaned
    if source_id == "semianalysis":
        blocked_patterns = [
            "Subscribe to get notified of all SemiAnalysis articles",
            "Please verify your email address to proceed.",
            "By subscribing, you agree to the Privacy Policy and Terms and Conditions",
            "With a SemiAnalysis subscription you’ll get access",
            "With a SemiAnalysis subscription you'll get access",
            "Model access not included",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "stratechery":
        blocked_patterns = [
            "Subscribe to Stratechery Plus for full access.",
            "$15 / month or $150 / year",
            "With Stratechery Plus you get access",
            "Learn More Member Forum",
            "Member Forum",
            "Subscribe to Stratechery Plus",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "anthropic-news":
        blocked_patterns = [
            "PwC will roll out Claude Code and Cowork",
            "We're launching Claude for Small Business",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "a16z-blog":
        blocked_patterns = [
            "Deep dives into what makes companies truly great",
            "Views expressed in “posts”",
            "The contents in here",
            "Under no circumstances should any posts",
            "There can be no assurances that a16z’s investment objectives",
            "With respect to funds managed by a16z that are registered in Japan",
            "For other site terms of use, please go here",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "36kr":
        blocked_patterns = [
            "本文来自微信公众号",
            "扫码关注",
            "来36氪Pro",
            "加入36氪",
            "关注获取更多",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "openai-blog":
        cleaned: list[str] = []
        label_pattern = re.compile(
            r"^(Company|Product|Research|Safety|Engineering|Security|Global Affairs|OpenAI Academy) "
            r"[A-Z][a-z]{2} \d{1,2}, \d{4}$"
        )
        for paragraph in paragraphs:
            if label_pattern.match(paragraph):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "y-combinator":
        blocked_patterns = [
            "Want to sign up for weekly updates from YC?",
            "Sign up for the newsletter",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", paragraph):
                continue
            if paragraph.startswith("Garry is the President & CEO of Y Combinator."):
                continue
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "unusual-whales":
        blocked_patterns = [
            "Create a free account here",
            "Do you want to see how to make more plays",
            "Want more market intelligence",
            "Unusual Whales helps you find market opportunities",
        ]
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if any(pattern.lower() in paragraph.lower() for pattern in blocked_patterns):
                continue
            cleaned.append(paragraph)
        return cleaned
    if source_id == "tradingview-news":
        cleaned: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) < 30 and not paragraph.endswith("."):
                continue
            cleaned.append(paragraph)
        return cleaned
    return paragraphs


def _extract_nikkei_next_data_paragraphs(html: str) -> list[str]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    body_html = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("data", {})
        .get("body", "")
    )
    if not isinstance(body_html, str) or not body_html.strip():
        return []

    soup = BeautifulSoup(body_html, "html.parser")
    paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
    paragraphs = [text for text in paragraphs if len(text) >= 20]
    return _filter_source_paragraphs("nikkei-asia", paragraphs)


def _extract_scmp_next_data_paragraphs(html: str) -> list[str]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    body_html = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("payload", {})
        .get("json", {})
        .get("data", {})
        .get("article", {})
        .get("body", {})
        .get("text", "")
    )
    if isinstance(body_html, str) and body_html.strip():
        # `text` is already plain text with paragraph breaks.
        paragraphs = [clean_text(p) for p in body_html.split("\n") if clean_text(p)]
        paragraphs = [text for text in paragraphs if len(text) >= 20]
        return _filter_source_paragraphs("scmp", paragraphs)
    return []


def _extract_unusual_whales_next_data_paragraphs(html: str) -> list[str]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    body_html = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("article", {})
        .get("html", "")
    )
    if not isinstance(body_html, str) or not body_html.strip():
        return []
    soup = BeautifulSoup(body_html, "html.parser")
    paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all(["p", "h2", "h3"])]
    paragraphs = [text for text in paragraphs if len(text) >= 20]
    return _filter_source_paragraphs("unusual-whales", paragraphs)


def _tradingview_node_text(node: object) -> str:
    if isinstance(node, str):
        return clean_text(node)
    if isinstance(node, list):
        return clean_text(" ".join(part for part in (_tradingview_node_text(child) for child in node) if part))
    if not isinstance(node, dict):
        return ""
    return clean_text(" ".join(part for part in (_tradingview_node_text(child) for child in node.get("children", [])) if part))


def _extract_tradingview_story_paragraphs(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all("script", attrs={"type": "application/prs.init-data+json"}):
        raw = node.string or node.get_text() or ""
        if '"ast_description"' not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        for value in payload.values():
            if not isinstance(value, dict):
                continue
            story = value.get("story")
            if not isinstance(story, dict):
                continue
            ast = story.get("ast_description")
            if not isinstance(ast, dict):
                continue
            paragraphs: list[str] = []
            for child in ast.get("children", []):
                if not isinstance(child, dict):
                    continue
                node_type = child.get("type")
                if node_type == "p":
                    text = _tradingview_node_text(child.get("children", []))
                    if text:
                        paragraphs.append(text)
                elif node_type == "list":
                    for item in child.get("children", []):
                        text = _tradingview_node_text(item)
                        if text:
                            paragraphs.append(text)
            paragraphs = [text for text in paragraphs if len(text) >= 20]
            if paragraphs:
                return _filter_source_paragraphs("tradingview-news", paragraphs)
    return []


def extract_candidate_paragraphs(source_id: str, html: str) -> list[str]:
    if source_id == "nikkei-asia":
        paragraphs = _extract_nikkei_next_data_paragraphs(html)
        if paragraphs:
            return paragraphs
    if source_id == "scmp":
        paragraphs = _extract_scmp_next_data_paragraphs(html)
        if paragraphs:
            return paragraphs
    if source_id == "unusual-whales":
        paragraphs = _extract_unusual_whales_next_data_paragraphs(html)
        if paragraphs:
            return paragraphs
    if source_id == "tradingview-news":
        paragraphs = _extract_tradingview_story_paragraphs(html)
        if paragraphs:
            return paragraphs

    soup = BeautifulSoup(html, "html.parser")
    for selector in STRIP_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    selectors = SOURCE_SELECTORS.get(source_id, ["article p", "main p", "p"])
    paragraphs: list[str] = []
    for selector in selectors:
        found = [clean_text(node.get_text(" ", strip=True)) for node in soup.select(selector)]
        found = [text for text in found if len(text) >= 20]
        if len(found) >= 1:
            paragraphs = found
            if len(found) >= 3:
                break

    if not paragraphs:
        found = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
        paragraphs = [text for text in found if len(text) >= 20]

    return _filter_source_paragraphs(source_id, paragraphs)


def _challenge_or_blocked(status: int | None, html: str) -> bool:
    if status in {401, 403}:
        return True
    lowered = (html or "").lower()
    blocked_markers = [
        "please enable js and disable any ad blocker",
        "captcha-delivery.com",
        "geo.captcha-delivery.com",
        "x-datadome",
        "verify you are human",
        "access denied",
    ]
    return any(marker in lowered for marker in blocked_markers)


def _reader_mirror_url(url: str) -> str:
    return f"https://r.jina.ai/http://{url}"


def _extract_reader_mirror_paragraphs(source_id: str, title: str, text: str) -> list[str]:
    marker = "Markdown Content:"
    body = text.split(marker, 1)[1] if marker in text else text
    body = body.replace("\r\n", "\n")

    if source_id == "wsj":
        heading = f"# {title}"
        start = body.rfind(heading)
        if start != -1:
            body = body[start:]
        stop_markers = [
            "\nContinue reading your article with",
            "\nAdvertisement",
            "\n[WSJ | Buy Side]",
            "\nWhat To Read Next",
        ]
        stop_indexes = [body.find(marker_text) for marker_text in stop_markers if body.find(marker_text) != -1]
        if stop_indexes:
            body = body[: min(stop_indexes)]

    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        block = clean_text(block)
        block = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", block).strip()
        block = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", block).strip()
        block = re.sub(r"^#+\s*", "", block).strip()
        if not block:
            continue
        paragraphs.append(block)
    return _filter_source_paragraphs(source_id, paragraphs)


def _fetch_reader_mirror_fulltext(item: IngestedItem, url: str) -> FulltextResult | None:
    if item.source_id not in MIRROR_ENABLED_SOURCES:
        return None

    mirror_url = _reader_mirror_url(url)
    try:
        response = requests.get(mirror_url, headers=HEADERS, timeout=MIRROR_REQUEST_TIMEOUT)
        status = response.status_code
        text = response.text
    except Exception:
        return None

    if status >= 400:
        return FulltextResult(
            source_id=item.source_id,
            title=item.title,
            canonical_url=url,
            http_status=status,
            paragraphs=[],
            classification="partial_only",
            note=f"mirror_http_{status}",
        )

    paragraphs = _extract_reader_mirror_paragraphs(item.source_id, item.title, text)
    if paragraphs:
        body_chars = sum(len(p) for p in paragraphs)
        if len(paragraphs) >= FULLTEXT_PARAGRAPH_THRESHOLD and body_chars >= FULLTEXT_CHAR_THRESHOLD:
            classification, note = "full_text_capable", "body_extracted_via_reader_mirror"
        elif len(paragraphs) >= 2 and body_chars >= 300:
            classification, note = "mixed", "partial_body_via_reader_mirror"
        else:
            classification, note = "partial_only", "mirror_body_too_short"
        return FulltextResult(
            source_id=item.source_id,
            title=item.title,
            canonical_url=url,
            http_status=200,
            paragraphs=paragraphs,
            classification=classification,
            note=note,
        )

    return FulltextResult(
        source_id=item.source_id,
        title=item.title,
        canonical_url=url,
        http_status=200,
        paragraphs=[],
        classification="partial_only",
        note="mirror_body_not_found",
    )


def _is_allowed_syndication_host(source_id: str, url: str) -> bool:
    allowed_hosts = SYNDICATED_FULLTEXT_HOSTS.get(source_id, [])
    if not allowed_hosts:
        return False
    hostname = urlparse(url).hostname or ""
    return any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts)


def _title_similarity(left: str, right: str) -> float:
    left_key = title_key(left)
    right_key = title_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key in right_key or right_key in left_key:
        return 1.0
    left_tokens = {token for token in left_key.split() if len(token) >= 3}
    right_tokens = {token for token in right_key.split() if len(token) >= 3}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _extract_rss_links(xml_text: str) -> list[tuple[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    links: list[tuple[str, str]] = []
    for item_node in root.findall(".//item"):
        title = item_node.findtext("title", default="")
        link = item_node.findtext("link", default="")
        if link:
            links.append((clean_text(title), link.strip()))
    return links


def _search_syndicated_fulltext_candidates(item: IngestedItem) -> list[str]:
    if item.source_id not in SYNDICATED_FULLTEXT_ENABLED_SOURCES:
        return []

    hosts = SYNDICATED_FULLTEXT_HOSTS.get(item.source_id, [])
    if not hosts:
        return []

    quoted_title = item.title.replace('"', "").replace("’", "'")
    host_query = " OR ".join(f"site:{host}" for host in hosts)
    candidates: list[str] = []
    title_tokens = title_key(item.title).split()
    loose_title = " ".join(title_tokens[:10])
    raw_queries = [
        f'({host_query}) "{quoted_title}" {item.byline or item.source_id}',
        f"({host_query}) {loose_title} {item.byline or item.source_id}",
    ]
    for raw_query in raw_queries:
        query = quote_plus(raw_query)
        search_url = f"https://www.bing.com/news/search?q={query}&format=RSS"
        try:
            response = requests.get(search_url, headers=HEADERS, timeout=SYNDICATED_SEARCH_TIMEOUT)
        except Exception:
            response = None

        if response is not None and response.status_code < 400:
            for result_title, link in _extract_rss_links(response.text):
                if not _is_allowed_syndication_host(item.source_id, link):
                    continue
                if _title_similarity(item.title, result_title) < SYNDICATED_TITLE_SIMILARITY_THRESHOLD:
                    continue
                if link not in candidates:
                    candidates.append(link)
                if len(candidates) >= SYNDICATED_CANDIDATE_LIMIT:
                    return candidates

        web_search_url = f"https://www.bing.com/search?q={query}"
        try:
            web_response = requests.get(web_search_url, headers=HEADERS, timeout=SYNDICATED_SEARCH_TIMEOUT)
        except Exception:
            continue
        if web_response.status_code >= 400:
            continue

        soup = BeautifulSoup(web_response.text, "html.parser")
        for anchor in soup.select("li.b_algo h2 a, h2 a, a"):
            link = str(anchor.get("href") or "").strip()
            result_title = clean_text(anchor.get_text(" ", strip=True))
            if not link.startswith("http"):
                continue
            if link in candidates:
                continue
            if not _is_allowed_syndication_host(item.source_id, link):
                continue
            if result_title and _title_similarity(item.title, result_title) < SYNDICATED_TITLE_SIMILARITY_THRESHOLD:
                continue
            candidates.append(link)
            if len(candidates) >= SYNDICATED_CANDIDATE_LIMIT:
                return candidates
    return candidates


def _extract_page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return clean_text(str(og_title["content"]))
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    if soup.title:
        return clean_text(soup.title.get_text(" ", strip=True))
    return ""


def _fetch_syndicated_fulltext(item: IngestedItem, canonical_url: str) -> FulltextResult | None:
    if item.source_id not in SYNDICATED_FULLTEXT_ENABLED_SOURCES:
        return None

    for syndicated_url in _search_syndicated_fulltext_candidates(item):
        try:
            response = requests.get(syndicated_url, headers=HEADERS, timeout=SYNDICATED_FETCH_TIMEOUT)
        except Exception:
            continue
        if response.status_code >= 400:
            continue
        if not response.encoding or response.encoding.lower() in {"iso-8859-1", "windows-1252"}:
            response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
        page_title = _extract_page_title(html)
        if _title_similarity(item.title, page_title) < SYNDICATED_TITLE_SIMILARITY_THRESHOLD:
            continue
        if item.source_id == "bloomberg" and "bloomberg" not in html.lower():
            continue

        extraction_source_id = f"msn-{item.source_id}"
        paragraphs = extract_candidate_paragraphs(extraction_source_id, html)
        paragraphs = _filter_source_paragraphs(item.source_id, paragraphs)
        classification, note = classify_page(response.status_code, paragraphs, html)
        if paragraphs and classification in {"full_text_capable", "mixed"}:
            return FulltextResult(
                source_id=item.source_id,
                title=item.title,
                canonical_url=canonical_url,
                http_status=response.status_code,
                paragraphs=paragraphs,
                classification=classification,
                note=f"syndicated_fulltext:{urlparse(syndicated_url).hostname}:{syndicated_url}",
            )

    return None


def classify_page(http_status: int | None, paragraphs: list[str], html: str) -> tuple[str, str]:
    if http_status is None:
        return "partial_only", "request_failed"
    if http_status >= 400:
        if http_status in {401, 403}:
            return "partial_only", f"http_{http_status}_blocked"
        return "partial_only", f"http_{http_status}"

    body_chars = sum(len(p) for p in paragraphs)
    paragraph_count = len(paragraphs)
    if paragraph_count >= FULLTEXT_PARAGRAPH_THRESHOLD and body_chars >= FULLTEXT_CHAR_THRESHOLD:
        return "full_text_capable", "body_extracted"
    if paragraph_count >= 1 and body_chars >= 180 and ("yicai.com" in html or "第一财经" in html):
        return "mixed", "short_article_body_extracted"
    if paragraph_count >= 2 and body_chars >= 300:
        lowered = html.lower()
        if "captcha" in lowered or "verify you are human" in lowered or "access denied" in lowered:
            return "mixed", "body_extracted_with_challenge_markers"
        return "mixed", "partial_body_extracted"
    lowered = html.lower()
    if "captcha" in lowered or "verify you are human" in lowered or "access denied" in lowered:
        return "partial_only", "challenge_or_access_denied"
    return "partial_only", "body_too_short"


def fetch_fulltext(item: IngestedItem) -> FulltextResult:
    if item.source_id == "github-trending":
        return FulltextResult(
            source_id=item.source_id,
            title=item.title,
            canonical_url=item.canonical_url or item.source_url,
            http_status=200,
            paragraphs=[],
            classification="partial_only",
            note="ranking_page_no_article_body",
        )

    if item.body_text.strip():
        paragraphs = [clean_text(p) for p in item.body_text.split("\n\n") if clean_text(p)]
        paragraphs = _filter_source_paragraphs(item.source_id, paragraphs)
        body_chars = sum(len(p) for p in paragraphs)
        if item.source_id == "y-combinator" and len(paragraphs) >= 1 and body_chars >= 500:
            classification, note = "full_text_capable", item.fulltext_note or "rss_content_encoded"
        elif len(paragraphs) >= FULLTEXT_PARAGRAPH_THRESHOLD and body_chars >= FULLTEXT_CHAR_THRESHOLD:
            classification, note = "full_text_capable", item.fulltext_note or "body_from_ingest"
        elif len(paragraphs) >= 2 and body_chars >= 300:
            classification, note = "mixed", item.fulltext_note or "partial_body_from_ingest"
        else:
            classification, note = "partial_only", item.fulltext_note or "body_too_short_from_ingest"
        return FulltextResult(
            source_id=item.source_id,
            title=item.title,
            canonical_url=item.canonical_url or item.source_url,
            http_status=200,
            paragraphs=paragraphs,
            classification=classification,
            note=note,
        )

    url = item.canonical_url or item.source_url
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        status = response.status_code
        if not response.encoding or response.encoding.lower() in {"iso-8859-1", "windows-1252"}:
            response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
    except Exception as exc:  # noqa: BLE001
        return FulltextResult(
            source_id=item.source_id,
            title=item.title,
            canonical_url=url,
            http_status=None,
            paragraphs=[],
            classification="partial_only",
            note=f"request_error:{exc.__class__.__name__}",
        )

    if _challenge_or_blocked(status, html):
        mirror_result = _fetch_reader_mirror_fulltext(item, url)
        if mirror_result is not None:
            return mirror_result

    paragraphs = extract_candidate_paragraphs(item.source_id, html)
    classification, note = classify_page(status, paragraphs, html)
    if classification != "full_text_capable":
        syndicated_result = _fetch_syndicated_fulltext(item, url)
        if syndicated_result is not None:
            return syndicated_result
    return FulltextResult(
        source_id=item.source_id,
        title=item.title,
        canonical_url=url,
        http_status=status,
        paragraphs=paragraphs,
        classification=classification,
        note=note,
    )
