#!/usr/bin/env python3
"""Enrich raw ingest items with full-text extraction fields."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.base import IngestedItem  # noqa: E402
from ingest.fulltext_tools import fetch_fulltext  # noqa: E402


def load_items(path: Path) -> list[IngestedItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [IngestedItem(**item) for item in raw]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sources",
        nargs="*",
        default=["ap", "bbc", "bloomberg", "cnbc", "caixin", "cailian", "yicai", "ft"],
        help="Only enrich these sources. Defaults to the currently most relevant set.",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=20,
        help="Safety cap for how many items per source to enrich.",
    )
    args = parser.parse_args()

    items = load_items(args.input)
    per_source_count: dict[str, int] = {}

    for item in items:
        if item.source_id not in args.sources:
            continue
        count = per_source_count.get(item.source_id, 0)
        if count >= args.max_per_source:
            continue
        result = fetch_fulltext(item)
        item.body_text = "\n\n".join(result.paragraphs)
        item.fulltext_status = result.classification
        item.fulltext_note = result.note
        per_source_count[item.source_id] = count + 1

    args.output.write_text(
        json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"output={args.output}")
    for source_id, count in sorted(per_source_count.items()):
        print(f"{source_id}={count}")


if __name__ == "__main__":
    main()
