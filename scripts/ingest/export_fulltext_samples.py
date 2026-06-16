#!/usr/bin/env python3
"""Export one full-text sample per source when extraction is stable enough."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.base import dedupe_items  # noqa: E402
from ingest.fulltext_tools import fetch_fulltext  # noqa: E402
from ingest.registry import build_adapters  # noqa: E402


def build_samples(source_ids: list[str], lookback_hours: int, per_source_limit: int) -> dict[str, dict[str, object]]:
    samples: dict[str, dict[str, object]] = {}
    adapters = build_adapters(source_ids, lookback_hours=lookback_hours)
    for adapter in adapters:
        try:
            items = dedupe_items(adapter.fetch())
        except Exception as exc:  # noqa: BLE001
            samples[adapter.source_id] = {"error": f"adapter_failed:{exc.__class__.__name__}"}
            continue

        chosen = None
        for item in items[:per_source_limit]:
            result = fetch_fulltext(item)
            if result.classification == "full_text_capable":
                chosen = {
                    "title": result.title,
                    "url": result.canonical_url,
                    "http_status": result.http_status,
                    "paragraph_count": result.paragraph_count,
                    "body_chars": result.body_chars,
                    "classification": result.classification,
                    "note": result.note,
                    "paragraphs": result.paragraphs,
                }
                break

        if chosen is None:
            samples[adapter.source_id] = {"error": "no_full_text_capable_sample_found"}
        else:
            samples[adapter.source_id] = chosen
    return samples


def render_markdown(samples: dict[str, dict[str, object]]) -> str:
    lines = ["# Stable Full-text Samples", ""]
    for source_id, payload in samples.items():
        lines.append(f"## {source_id}")
        if "error" in payload:
            lines.append(f"- Status: {payload['error']}")
            lines.append("")
            continue

        lines.extend(
            [
                f"- Title: {payload['title']}",
                f"- URL: {payload['url']}",
                f"- HTTP status: {payload['http_status']}",
                f"- Paragraphs: {payload['paragraph_count']}",
                f"- Characters: {payload['body_chars']}",
                f"- Classification: {payload['classification']}",
                f"- Note: {payload['note']}",
                "",
                "### Full Text",
                "",
            ]
        )
        for paragraph in payload["paragraphs"]:
            lines.append(str(paragraph))
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["ap", "bbc", "cnbc", "caixin"],
        help="Sources to export stable full-text samples for.",
    )
    parser.add_argument("--lookback-hours", type=int, default=96)
    parser.add_argument("--per-source-limit", type=int, default=10)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "artifacts" / "stable-fulltext-samples.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "artifacts" / "stable-fulltext-samples.md",
    )
    args = parser.parse_args()

    samples = build_samples(args.sources, args.lookback_hours, args.per_source_limit)
    args.output_json.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(samples), encoding="utf-8")
    print(f"json={args.output_json}")
    print(f"markdown={args.output_md}")
    for source_id, payload in samples.items():
        print(source_id, "ok" if "error" not in payload else payload["error"])


if __name__ == "__main__":
    main()
