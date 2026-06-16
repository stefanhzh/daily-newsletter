#!/usr/bin/env python3
"""Inspect Caixin front-end requests with Playwright.

Use this as a reconnaissance tool, not a production ingestion job.
It helps us find cleaner feeds, XHR endpoints, and request headers that
can later be migrated into a lightweight Python adapter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "artifacts" / "caixin-playwright-recon.json"
DEFAULT_URLS = [
    "https://www.caixinglobal.com/",
    "https://www.caixinglobal.com/world/",
    "https://www.caixinglobal.com/economy/",
    "https://www.caixinglobal.com/china/",
    "https://www.caixinglobal.com/finance/",
    "https://www.caixinglobal.com/business-and-tech/",
    "https://www.caixinglobal.com/news/",
]
INTERESTING_HINTS = (
    "feed",
    "rss",
    "api",
    "ajax",
    "json",
    "recommend",
    "gateway",
    "mapi",
)
ALLOWED_HOST_SUFFIXES = (
    "caixinglobal.com",
    "caixin.com",
    "file.caixin.com",
    "gateway.caixin.com",
    "mapi.caixinglobal.com",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--urls", nargs="*", default=DEFAULT_URLS)
    args = parser.parse_args()

    payload = inspect_urls(args.urls, timeout_ms=args.timeout_ms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"output={args.output}")
    print(f"pages={len(payload['pages'])}")
    print(f"interesting_requests={len(payload['interesting_requests'])}")


def inspect_urls(urls: list[str], *, timeout_ms: int) -> dict[str, object]:
    page_payloads: list[dict[str, object]] = []
    interesting_requests: list[dict[str, object]] = []
    seen_request_keys: set[tuple[str, str]] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
            )
        )

        for url in urls:
            page = context.new_page()
            network_log: list[dict[str, object]] = []
            response_log: dict[str, dict[str, object]] = {}

            def on_request(request) -> None:
                network_log.append(
                    {
                        "url": request.url,
                        "resource_type": request.resource_type,
                        "method": request.method,
                    }
                )

            def on_response(response) -> None:
                headers = response.headers
                response_log[response.url] = {
                    "status": response.status,
                    "content_type": headers.get("content-type", ""),
                }

            page.on("request", on_request)
            page.on("response", on_response)

            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception as exc:
                page_payloads.append({"url": url, "error": str(exc), "interesting_count": 0})
                page.close()
                continue

            page_title = page.title()
            html = page.content()
            found_urls = sorted(set(re.findall(r"https://[^\"'\\s<>]+", html)))
            page_interesting = summarize_interesting(network_log, response_log, source_page=url)
            page_payloads.append(
                {
                    "url": url,
                    "title": page_title,
                    "interesting_count": len(page_interesting),
                    "html_urls_sample": found_urls[:20],
                }
            )

            for item in page_interesting:
                request_key = (item["url"], item["source_page"])
                if request_key in seen_request_keys:
                    continue
                seen_request_keys.add(request_key)
                interesting_requests.append(item)

            page.close()

        browser.close()

    interesting_requests.sort(key=lambda item: (item["source_page"], item["url"]))
    return {"pages": page_payloads, "interesting_requests": interesting_requests}


def summarize_interesting(
    requests: list[dict[str, object]],
    responses: dict[str, dict[str, object]],
    *,
    source_page: str,
) -> list[dict[str, object]]:
    interesting: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for request in requests:
        request_url = str(request["url"])
        if request_url in seen_urls:
            continue
        if not _looks_interesting(request_url):
            continue
        seen_urls.add(request_url)
        meta = responses.get(request_url, {})
        interesting.append(
            {
                "source_page": source_page,
                "url": request_url,
                "method": request["method"],
                "resource_type": request["resource_type"],
                "status": meta.get("status"),
                "content_type": meta.get("content_type", ""),
            }
        )

    return interesting


def _looks_interesting(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        return False
    lowered = url.lower()
    return any(hint in lowered for hint in INTERESTING_HINTS)


if __name__ == "__main__":
    main()
