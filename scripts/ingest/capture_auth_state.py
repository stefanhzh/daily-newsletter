#!/usr/bin/env python3
"""Capture a Playwright storage_state file after manual login."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.auth_state import storage_state_path  # noqa: E402
from ingest.base import DEFAULT_USER_AGENT  # noqa: E402


LOGIN_URLS = {
    "zhihu-hot": "https://www.zhihu.com/hot",
    "xiaohongshu-search": "https://www.xiaohongshu.com/explore",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=sorted(LOGIN_URLS))
    parser.add_argument("--url", help="Override the login URL.")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=120,
        help="How long to keep the browser open before saving storage_state.",
    )
    parser.add_argument(
        "--channel",
        default="chrome",
        help="Browser channel to use, for example chrome, msedge, or chromium.",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(f"Playwright is required to capture auth state: {exc}") from exc

    output = storage_state_path(args.source)
    output.parent.mkdir(parents=True, exist_ok=True)
    url = args.url or LOGIN_URLS[args.source]

    profile_dir = output.parent / f"{args.source}.profile"

    with sync_playwright() as p:
        launch_options = {
            "headless": False,
            "user_agent": DEFAULT_USER_AGENT,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport": {"width": 1280, "height": 900},
        }
        if args.channel and args.channel != "chromium":
            launch_options["channel"] = args.channel

        context = p.chromium.launch_persistent_context(str(profile_dir), **launch_options)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            print(f"Opened {url}")
            print(f"Please log in if needed. Saving auth state in {args.wait_seconds} seconds...")
            page.wait_for_timeout(args.wait_seconds * 1000)
            context.storage_state(path=str(output))
            print(f"saved={output}")
        finally:
            context.close()


if __name__ == "__main__":
    main()
