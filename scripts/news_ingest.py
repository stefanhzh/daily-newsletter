#!/usr/bin/env python3
"""Reusable source-ingestion CLI with static HTML and Markdown preview output."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import escape
import json
import multiprocessing as mp
from pathlib import Path
import queue as queue_module
import sys
from typing import Any
from urllib.parse import urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ingest.base import IngestedItem, dedupe_items  # noqa: E402
from ingest.registry import ADAPTERS, build_adapters  # noqa: E402


PRESETS_PATH = ROOT / "config" / "source_presets.json"
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.json"
REPORTS_DIR = ROOT / "reports" / "source_ingest"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def load_source_catalog() -> dict[str, dict[str, Any]]:
    if not SOURCES_CONFIG_PATH.exists():
        return {}
    config = load_json(SOURCES_CONFIG_PATH)
    catalog: dict[str, dict[str, Any]] = {}
    for source in config.get("sources", []):
        source_id = source.get("id", "")
        if not source_id:
            continue
        catalog[source_id] = source
        for alias in source.get("aliases", []):
            catalog.setdefault(alias, source)
    return catalog


def adapter_id_for(source_id: str, catalog: dict[str, dict[str, Any]]) -> str:
    if source_id in ADAPTERS:
        return source_id
    source = catalog.get(source_id) or {}
    candidates = [source.get("id", "")] + source.get("aliases", [])
    for candidate in candidates:
        if candidate in ADAPTERS:
            return candidate
    return source_id


def source_label(source_id: str, catalog: dict[str, dict[str, Any]]) -> str:
    source = catalog.get(source_id) or {}
    return source.get("name") or source_id


def load_presets() -> dict[str, Any]:
    if not PRESETS_PATH.exists():
        return {}
    return load_json(PRESETS_PATH)


def parse_source_spec(value: str) -> tuple[str, int]:
    if ":" not in value:
        return value.strip(), 20
    source_id, raw_limit = value.split(":", 1)
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 20
    return source_id.strip(), max(1, limit)


def requested_sources(args: argparse.Namespace, presets: dict[str, Any]) -> tuple[list[dict[str, Any]], int, str]:
    if args.sources:
        return (
            [{"id": source_id, "limit": limit} for source_id, limit in map(parse_source_spec, args.sources)],
            args.lookback_hours or 24,
            "manual",
        )

    preset = presets.get(args.preset)
    if not preset:
        available = ", ".join(sorted(presets)) or "none"
        raise SystemExit(f"Unknown preset: {args.preset}. Available presets: {available}")
    lookback_hours = args.lookback_hours or int(preset.get("lookback_hours", 24))
    return list(preset.get("sources", [])), lookback_hours, args.preset


def item_rank_key(item: IngestedItem) -> tuple[int, str, str]:
    rank = item.rank_position if item.rank_position and item.rank_position > 0 else 999999
    # Ranked/homepage adapters should keep page order; non-ranked feeds fall back to newest first.
    return (rank, reverse_sortable_time(item.published_at), item.title)


def reverse_sortable_time(value: str) -> str:
    # String trick for stable sort: valid ISO dates sort ascending; prefix inversion happens below.
    return value or ""


def sort_items_for_source(items: list[IngestedItem]) -> list[IngestedItem]:
    ranked = [item for item in items if item.rank_position and item.rank_position > 0]
    unranked = [item for item in items if not item.rank_position]
    ranked.sort(key=lambda item: (item.rank_position, item.published_at or "", item.title))
    unranked.sort(key=lambda item: (item.published_at or "", item.title), reverse=True)
    return ranked + unranked


def fetch_adapter_items(adapter_id: str, lookback_hours: int) -> tuple[list[IngestedItem], str, str]:
    adapter = build_adapters([adapter_id], lookback_hours=lookback_hours)[0]
    try:
        return adapter.fetch(), "ok", ""
    except Exception as exc:  # noqa: BLE001
        return [], "failed", f"{exc.__class__.__name__}: {exc}"


def fetch_adapter_worker(adapter_id: str, lookback_hours: int, queue: mp.Queue) -> None:
    fetched, status, error = fetch_adapter_items(adapter_id, lookback_hours)
    queue.put(([item.to_dict() for item in fetched], status, error))


def fetch_adapter_items_with_timeout(
    adapter_id: str,
    lookback_hours: int,
    source_timeout: int,
) -> tuple[list[IngestedItem], str, str]:
    if source_timeout <= 0:
        return fetch_adapter_items(adapter_id, lookback_hours)

    queue: mp.Queue = mp.Queue()
    process = mp.Process(target=fetch_adapter_worker, args=(adapter_id, lookback_hours, queue))
    process.start()
    try:
        fetched_dicts, status, error = queue.get(timeout=source_timeout)
    except queue_module.Empty:
        process.terminate()
        process.join(3)
        return [], "timeout", f"Source fetch exceeded {source_timeout}s timeout."

    process.join(3)
    if process.is_alive():
        process.terminate()
        process.join(3)

    fetched = [IngestedItem(**item) for item in fetched_dicts]
    return fetched, status, error


def fetch_adapter_group(
    adapter_id: str,
    specs: list[dict[str, Any]],
    lookback_hours: int,
    catalog: dict[str, dict[str, Any]],
    source_timeout: int,
) -> tuple[list[IngestedItem], list[dict[str, Any]]]:
    requested_limit = max(int(spec.get("limit", 20)) for spec in specs)
    source_ids = [spec.get("id", adapter_id) for spec in specs]
    if adapter_id not in ADAPTERS:
        summaries = []
        for source_id in source_ids:
            summaries.append(
                {
                    "source_id": source_id,
                    "adapter_id": adapter_id,
                    "source_name": source_label(source_id, catalog),
                    "requested_limit": requested_limit,
                    "raw_count": 0,
                    "output_count": 0,
                    "status": "missing_adapter",
                    "error": "No adapter registered for this source.",
                }
            )
        return [], summaries

    fetched, status, error = fetch_adapter_items_with_timeout(adapter_id, lookback_hours, source_timeout)
    sorted_items = sort_items_for_source(dedupe_items(fetched))
    limited = sorted_items[:requested_limit]
    summary = {
        "source_id": limited[0].source_id if limited else source_ids[0],
        "adapter_id": adapter_id,
        "source_name": source_label(source_ids[0], catalog),
        "requested_limit": requested_limit,
        "raw_count": len(fetched),
        "output_count": len(limited),
        "status": status,
        "error": error,
    }
    return limited, [summary]


def fetch_items(
    source_specs: list[dict[str, Any]],
    lookback_hours: int,
    catalog: dict[str, dict[str, Any]],
    source_timeout: int = 0,
    jobs: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    adapter_to_specs: dict[str, list[dict[str, Any]]] = {}
    for spec in source_specs:
        source_id = spec.get("id", "")
        adapter_id = adapter_id_for(source_id, catalog)
        if adapter_id not in ADAPTERS:
            adapter_to_specs.setdefault(adapter_id, []).append(spec)
            continue
        adapter_to_specs.setdefault(adapter_id, []).append(spec)

    raw_items: list[IngestedItem] = []
    summaries: list[dict[str, Any]] = []
    adapter_groups = list(adapter_to_specs.items())
    if jobs <= 1:
        for adapter_id, specs in adapter_groups:
            limited, group_summaries = fetch_adapter_group(adapter_id, specs, lookback_hours, catalog, source_timeout)
            raw_items.extend(limited)
            summaries.extend(group_summaries)
    else:
        ordered_results: list[tuple[list[IngestedItem], list[dict[str, Any]]] | None] = [None] * len(adapter_groups)
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            future_to_index = {
                executor.submit(fetch_adapter_group, adapter_id, specs, lookback_hours, catalog, source_timeout): index
                for index, (adapter_id, specs) in enumerate(adapter_groups)
            }
            for future in as_completed(future_to_index):
                ordered_results[future_to_index[future]] = future.result()
        for result in ordered_results:
            if result is None:
                continue
            limited, group_summaries = result
            raw_items.extend(limited)
            summaries.extend(group_summaries)

    payload_items = [item.to_dict() for item in dedupe_items(raw_items)]
    return payload_items, summaries


def source_counts(items: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        counts[item.get("source_id", "")] += 1
    return counts


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def default_output_dir() -> Path:
    stamp = now_local().strftime("%Y-%m-%d_%H-%M-%S")
    return REPORTS_DIR / stamp


def write_outputs(output_dir: Path, run_payload: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_items.json"
    summary_path = output_dir / "source_summary.json"
    html_path = output_dir / "index.html"
    markdown_path = output_dir / "report.md"
    raw_path.write_text(json.dumps(run_payload["items"], ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(run_payload), encoding="utf-8")
    markdown_path.write_text(render_markdown(run_payload), encoding="utf-8")
    return raw_path, summary_path, html_path, markdown_path


def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def render_html(payload: dict[str, Any]) -> str:
    items = payload["items"]
    summaries = payload["source_summaries"]
    counts = source_counts(items)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get("source_id", "unknown"), []).append(item)

    source_cards = "\n".join(render_source_card(summary, counts) for summary in summaries)
    sections = "\n".join(render_source_section(source_id, grouped[source_id]) for source_id in sorted(grouped))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>News Source Ingest Preview</title>
  <style>
    :root {{
      --ink: #17211b;
      --muted: #6d766f;
      --paper: #f7f1e6;
      --card: rgba(255, 252, 244, 0.86);
      --line: rgba(31, 46, 38, 0.14);
      --accent: #0b6f63;
      --accent-2: #c76d28;
      --bad: #a33d2f;
      --shadow: 0 24px 80px rgba(34, 43, 35, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 0%, rgba(199,109,40,0.18), transparent 28rem),
        radial-gradient(circle at 88% 10%, rgba(11,111,99,0.16), transparent 30rem),
        linear-gradient(135deg, #f8efe0 0%, #eef4ee 100%);
    }}
    header {{
      padding: 56px min(7vw, 88px) 26px;
    }}
    .eyebrow {{
      color: var(--accent);
      font: 700 12px/1.2 "Trebuchet MS", sans-serif;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    h1 {{
      max-width: 900px;
      margin: 12px 0 12px;
      font-size: clamp(36px, 6vw, 76px);
      line-height: 0.96;
      letter-spacing: -0.05em;
    }}
    .meta {{
      max-width: 900px;
      color: var(--muted);
      font: 15px/1.7 "Trebuchet MS", sans-serif;
    }}
    main {{
      padding: 0 min(7vw, 88px) 72px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin: 22px 0 34px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .card strong {{
      display: block;
      font-size: 18px;
      margin-bottom: 8px;
    }}
    .card span {{
      display: inline-flex;
      margin: 5px 8px 0 0;
      color: var(--muted);
      font: 12px/1.2 "Trebuchet MS", sans-serif;
    }}
    .status-failed, .status-missing_adapter {{ color: var(--bad) !important; }}
    .source-section {{
      margin: 28px 0;
      background: rgba(255,255,255,0.54);
      border: 1px solid var(--line);
      border-radius: 28px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }}
    .source-head {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      padding: 20px 22px;
      background: rgba(255, 252, 244, 0.7);
      border-bottom: 1px solid var(--line);
    }}
    .source-head h2 {{
      margin: 0;
      font-size: 26px;
      letter-spacing: -0.03em;
    }}
    .items {{
      display: grid;
      gap: 0;
    }}
    article {{
      display: grid;
      grid-template-columns: 72px 1fr;
      gap: 16px;
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
    }}
    article:last-child {{ border-bottom: 0; }}
    .rank {{
      width: 48px;
      height: 48px;
      display: grid;
      place-items: center;
      border-radius: 16px;
      background: #173d36;
      color: #fff8eb;
      font: 700 14px/1 "Trebuchet MS", sans-serif;
    }}
    .rank.feed {{ background: #94745a; }}
    h3 {{
      margin: 0 0 8px;
      font-size: 19px;
      line-height: 1.25;
      letter-spacing: -0.02em;
    }}
    a {{ color: var(--ink); text-decoration-color: rgba(11,111,99,0.45); text-underline-offset: 3px; }}
    p {{
      margin: 0 0 10px;
      color: #35423a;
      font: 14px/1.62 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--muted);
      font: 12px/1.2 "Trebuchet MS", sans-serif;
    }}
    .chip {{
      padding: 5px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.54);
    }}
    @media (max-width: 680px) {{
      article {{ grid-template-columns: 1fr; }}
      .source-head {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Source Ingestion Console</div>
    <h1>News source intake preview</h1>
    <div class="meta">
      Preset: <strong>{escape(payload["run_meta"]["preset"])}</strong> ·
      Lookback: <strong>{payload["run_meta"]["lookback_hours"]}h</strong> ·
      Sources: <strong>{len(summaries)}</strong> ·
      Items: <strong>{len(items)}</strong> ·
      Generated: <strong>{escape(payload["run_meta"]["generated_at"])}</strong>
    </div>
  </header>
  <main>
    <section class="cards">{source_cards}</section>
    {sections}
  </main>
</body>
</html>
"""


def render_source_card(summary: dict[str, Any], counts: Counter[str]) -> str:
    source_id = summary["source_id"]
    status = summary["status"]
    error = summary.get("error", "")
    return f"""<div class="card">
  <strong>{escape(summary["source_name"])}</strong>
  <span>ID: {escape(source_id)}</span>
  <span class="status-{escape(status)}">Status: {escape(status)}</span>
  <span>Limit: {summary["requested_limit"]}</span>
  <span>Fetched: {summary["raw_count"]}</span>
  <span>Shown: {counts.get(source_id, summary["output_count"])}</span>
  {f'<span class="status-failed">Error: {escape(error[:120])}</span>' if error else ''}
</div>"""


def markdown_escape(value: Any) -> str:
    text = str(value or "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(payload: dict[str, Any]) -> str:
    items = payload["items"]
    summaries = payload["source_summaries"]
    counts = source_counts(items)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get("source_id", "unknown"), []).append(item)

    lines = [
        "# News Source Ingest Preview",
        "",
        f"- Preset: `{payload['run_meta']['preset']}`",
        f"- Lookback: `{payload['run_meta']['lookback_hours']}h`",
        f"- Sources: `{len(summaries)}`",
        f"- Items: `{len(items)}`",
        f"- Generated: `{payload['run_meta']['generated_at']}`",
        "",
        "## Source Summary",
        "",
        "| Source | Status | Limit | Fetched | Shown | Note |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]

    for summary in summaries:
        source_id = summary["source_id"]
        note = summary.get("error") or ""
        lines.append(
            "| {source} | {status} | {limit} | {fetched} | {shown} | {note} |".format(
                source=markdown_escape(summary["source_name"]),
                status=markdown_escape(summary["status"]),
                limit=summary["requested_limit"],
                fetched=summary["raw_count"],
                shown=counts.get(source_id, summary["output_count"]),
                note=markdown_escape(note[:160]),
            )
        )

    for source_id in sorted(grouped):
        lines.extend(["", f"## {source_id}", ""])
        for idx, item in enumerate(grouped[source_id], start=1):
            url = item.get("canonical_url") or item.get("source_url") or ""
            rank = item.get("rank_position") or idx
            title = item.get("title") or "(untitled)"
            summary = (item.get("summary") or "").strip()
            if len(summary) > 420:
                summary = summary[:420] + "..."
            meta_parts = [
                f"rank #{rank}",
                item.get("published_at", ""),
                item.get("rank_section") or item.get("section", ""),
                item.get("discovery_method", ""),
                host_of(url),
            ]
            meta = " | ".join(str(part) for part in meta_parts if part)
            lines.append(f"{idx}. [{title}]({url})")
            if meta:
                lines.append(f"   - {meta}")
            if summary:
                lines.append(f"   - {summary}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_source_section(source_id: str, items: list[dict[str, Any]]) -> str:
    rows = "\n".join(render_item(item, idx) for idx, item in enumerate(items, start=1))
    return f"""<section class="source-section">
  <div class="source-head">
    <h2>{escape(source_id)}</h2>
    <div class="meta">{len(items)} items</div>
  </div>
  <div class="items">{rows}</div>
</section>"""


def render_item(item: dict[str, Any], idx: int) -> str:
    url = item.get("canonical_url") or item.get("source_url") or ""
    rank = item.get("rank_position") or idx
    rank_class = "" if item.get("rank_position") else " feed"
    summary = escape((item.get("summary") or "").strip())
    if len(summary) > 360:
        summary = summary[:360] + "..."
    chips = [
        item.get("published_at", ""),
        item.get("rank_section") or item.get("section", ""),
        item.get("discovery_method", ""),
        host_of(url),
    ]
    chip_html = "".join(f'<span class="chip">{escape(str(chip))}</span>' for chip in chips if chip)
    return f"""<article>
  <div class="rank{rank_class}">#{escape(str(rank))}</div>
  <div>
    <h3><a href="{escape(url)}" target="_blank" rel="noreferrer">{escape(item.get("title", ""))}</a></h3>
    {f'<p>{summary}</p>' if summary else ''}
    <div class="chips">{chip_html}</div>
  </div>
</article>"""


def list_sources(catalog: dict[str, dict[str, Any]]) -> None:
    rows = []
    for adapter_id in sorted(ADAPTERS):
        source = catalog.get(adapter_id, {})
        rows.append((adapter_id, source.get("name", adapter_id), source.get("tier", ""), source.get("fetch_method", "")))
    for adapter_id, name, tier, fetch_method in rows:
        print(f"{adapter_id}\t{name}\t{tier}\t{fetch_method}")


def build_run_payload(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    presets = load_presets()
    catalog = load_source_catalog()
    if args.list_sources:
        list_sources(catalog)
        raise SystemExit(0)

    source_specs, lookback_hours, preset_name = requested_sources(args, presets)
    items, summaries = fetch_items(
        source_specs,
        lookback_hours,
        catalog,
        source_timeout=args.source_timeout,
        jobs=args.jobs,
    )
    generated_at = now_local().isoformat(timespec="seconds")
    output_dir = args.output_dir or default_output_dir()
    payload = {
        "run_meta": {
            "generated_at": generated_at,
            "preset": preset_name,
            "lookback_hours": lookback_hours,
            "requested_sources": source_specs,
        },
        "source_summaries": summaries,
        "items": items,
    }
    return payload, output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch configured news sources and render static HTML/Markdown previews. "
            "No --sources means the default preset is used."
        )
    )
    parser.add_argument("--preset", default="default", help="Preset name from config/source_presets.json.")
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Manual source specs such as reuters:20 bbc:10 caixin:15. Overrides preset.",
    )
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--output-dir", type=Path, help="Report output directory. Defaults to reports/source_ingest/<timestamp>.")
    parser.add_argument(
        "--source-timeout",
        type=int,
        default=0,
        help="Per-source timeout in seconds. Use 0 to disable timeout isolation.",
    )
    parser.add_argument("--jobs", type=int, default=1, help="Number of source groups to fetch concurrently.")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML report in the default browser.")
    parser.add_argument("--list-sources", action="store_true", help="List registered adapter source IDs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload, output_dir = build_run_payload(args)
    raw_path, summary_path, html_path, markdown_path = write_outputs(output_dir, payload)
    print(f"output_dir={output_dir}")
    print(f"raw_items={raw_path}")
    print(f"source_summary={summary_path}")
    print(f"html={html_path}")
    print(f"markdown={markdown_path}")
    print(f"total_items={len(payload['items'])}")
    for summary in payload["source_summaries"]:
        print(
            "{source_id} status={status} fetched={raw_count} shown={output_count} limit={requested_limit}".format(
                **summary
            )
        )
    if args.open:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
