#!/usr/bin/env python3
"""Run source ingestion adapters and export raw candidate items."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.base import dedupe_items  # noqa: E402
from ingest.registry import build_adapters  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["reuters", "ap"],
        help="Source ids to ingest.",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="Lookback window used by adapters.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "raw_ingest_latest.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    items = []
    stats: Counter[str] = Counter()
    for adapter in build_adapters(args.sources, lookback_hours=args.lookback_hours):
        try:
            adapter_items = adapter.fetch()
        except Exception as exc:
            print(f"[warn] {adapter.source_id} failed: {exc}")
            continue
        items.extend(adapter_items)
        stats[adapter.source_id] += len(adapter_items)

    deduped = dedupe_items(items)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in deduped]
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"output={args.output}")
    print(f"total_items={len(deduped)}")
    for source_id, count in sorted(stats.items()):
        print(f"{source_id}={count}")


if __name__ == "__main__":
    main()
