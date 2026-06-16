#!/usr/bin/env python3
"""One-off verifier for source full-text accessibility.

This script samples recent items from existing adapters, fetches article pages,
tries to extract body text, and summarizes whether each source is currently:
- full_text_capable
- mixed
- partial_only

It is intentionally heuristic and meant for operational validation rather than
perfect article parsing.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.base import IngestedItem, dedupe_items  # noqa: E402
from ingest.fulltext_tools import fetch_fulltext  # noqa: E402
from ingest.registry import ADAPTERS, build_adapters  # noqa: E402

@dataclass
class SampleResult:
    source_id: str
    title: str
    canonical_url: str
    http_status: int | None
    paragraph_count: int
    body_chars: int
    classification: str
    note: str

def _fetch_one(item: IngestedItem) -> SampleResult:
    result = fetch_fulltext(item)
    return SampleResult(
        source_id=result.source_id,
        title=result.title,
        canonical_url=result.canonical_url,
        http_status=result.http_status,
        paragraph_count=result.paragraph_count,
        body_chars=result.body_chars,
        classification=result.classification,
        note=result.note,
    )


def _source_summary(results: list[SampleResult]) -> dict[str, object]:
    counts = Counter(result.classification for result in results)
    note_counts = Counter(result.note for result in results)
    if counts["full_text_capable"] == len(results):
        overall = "可抓全文"
    elif counts["full_text_capable"] == 0 and counts["mixed"] == 0:
        overall = "只能抓取部分信息"
    else:
        overall = "部分可抓全文"
    return {
        "overall": overall,
        "sampled_articles": len(results),
        "classification_counts": dict(counts),
        "note_counts": dict(note_counts),
        "sample_results": [asdict(result) for result in results],
    }


def _fetch_samples(source_ids: list[str], lookback_hours: int, sample_size: int) -> dict[str, list[IngestedItem]]:
    sampled: dict[str, list[IngestedItem]] = defaultdict(list)
    adapters = build_adapters(source_ids, lookback_hours=lookback_hours)
    for adapter in adapters:
        try:
            items = dedupe_items(adapter.fetch())
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {adapter.source_id} adapter failed: {exc}")
            continue
        sampled[adapter.source_id] = items[:sample_size]
    return sampled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources",
        nargs="+",
        default=sorted(ADAPTERS.keys()),
        help="Source ids to test. Defaults to all registered adapters.",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=48,
        help="Lookback window for fetching candidate items.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="How many recent articles per source to sample.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "artifacts" / "fulltext-capability-report.json",
        help="JSON output path.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "artifacts" / "fulltext-capability-report.md",
        help="Markdown output path.",
    )
    args = parser.parse_args()

    sampled = _fetch_samples(args.sources, args.lookback_hours, args.sample_size)
    report: dict[str, object] = {
        "lookback_hours": args.lookback_hours,
        "sample_size": args.sample_size,
        "sources": {},
    }

    md_lines = [
        "# Full-text Capability Report",
        "",
        f"- Lookback hours: {args.lookback_hours}",
        f"- Sample size per source: {args.sample_size}",
        "",
    ]

    for source_id in args.sources:
        items = sampled.get(source_id, [])
        if not items:
            source_report = {
                "overall": "无样本",
                "sampled_articles": 0,
                "classification_counts": {},
                "note_counts": {"no_recent_items": 1},
                "sample_results": [],
            }
            report["sources"][source_id] = source_report
            md_lines.extend([f"## {source_id}", "- Overall: 无样本", "- Note: no_recent_items", ""])
            continue

        results = [_fetch_one(item) for item in items]
        source_report = _source_summary(results)
        report["sources"][source_id] = source_report

        md_lines.extend(
            [
                f"## {source_id}",
                f"- Overall: {source_report['overall']}",
                f"- Sampled articles: {source_report['sampled_articles']}",
                f"- Classification counts: {source_report['classification_counts']}",
                f"- Notes: {source_report['note_counts']}",
            ]
        )
        for result in results:
            md_lines.append(
                f"- {result.title} | status={result.http_status} | class={result.classification} | "
                f"paragraphs={result.paragraph_count} | chars={result.body_chars} | note={result.note}"
            )
        md_lines.append("")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"json={args.output_json}")
    print(f"markdown={args.output_md}")
    for source_id, source_report in report["sources"].items():
        print(f"{source_id}={source_report['overall']}")


if __name__ == "__main__":
    main()
