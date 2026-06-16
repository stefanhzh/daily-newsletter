#!/usr/bin/env python3
"""Render scored candidate-pool JSON as category-grouped HTML."""

from __future__ import annotations

import argparse
from collections import defaultdict
from html import escape
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from localization import (  # noqa: E402
    build_translations,
    category_label,
    clean_text,
    localized_related_title,
    localized_summary,
    localized_title,
    zh,
)
from tech_dynamics import (  # noqa: E402
    ITEMS_UNIT,
    RANK_LABEL,
    SOURCE_LABEL,
    TECH_DYNAMICS_NOTE,
    TECH_DYNAMICS_TITLE,
    ZH_SUMMARY_LABEL,
    ZH_TITLE_LABEL,
    build_tech_dynamics,
    item_summary_zh,
    item_title_zh,
    resolve_raw_items_path,
    translation_targets as tech_translation_targets,
)


DEFAULT_EXCLUDE_TITLES = {
    "Do you find yourself aimlessly scrolling? You're not alone",
}

CATEGORY_ORDER = [
    zh(r"\u5730\u7f18\u653f\u6cbb"),
    zh(r"\u5b8f\u89c2\u7ecf\u6d4e"),
    zh(r"\u4ea7\u4e1a\u8d8b\u52bf"),
    zh(r"\u8d44\u672c\u5e02\u573a\u4e0e\u4ea4\u6613"),
    zh(r"\u79d1\u6280\u8fdb\u5c55"),
    zh(r"\u653f\u7b56\u76d1\u7ba1"),
    zh(r"\u98ce\u9669\u4e8b\u4ef6"),
]
TECH_AFTER_CATEGORY = zh(r"\u79d1\u6280\u8fdb\u5c55")


PAGE_TITLE = zh(r"\u6309\u5206\u7c7b\u6574\u7406\u7684\u5019\u9009\u65b0\u95fb")
MAX_PER_CATEGORY = zh(r"\u6bcf\u7c7b\u6700\u591a")
CATEGORY = zh(r"\u5206\u7c7b")
DISPLAY = zh(r"\u5c55\u793a")
EXCLUDED = zh(r"\u5df2\u6392\u9664")
ITEM_UNIT = zh(r"\u6761")
ZH_TITLE = zh(r"\u4e2d\u6587\u6807\u9898")
ZH_SUMMARY = zh(r"\u4e2d\u6587\u6458\u8981")
ORIGINAL_SUMMARY = zh(r"\u539f\u6587\u6458\u8981")
RELATED = zh(r"\u76f8\u5173\u62a5\u9053")
CLUSTER_MEMBERS = zh(r"\u805a\u7c7b\u6210\u5458")
RULE = zh(r"\u89c4\u5219")
MODEL = zh(r"\u6a21\u578b")
MIDDLE_STATS = zh(r"\u4e2d\u95f4\u4fe1\u606f / \u7edf\u8ba1")
OPEN_ORIGINAL = zh(r"\u6253\u5f00\u539f\u6587")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--translation-cache",
        type=Path,
        default=ROOT / "reports" / "scoring" / "translation_cache.json",
    )
    parser.add_argument("--per-category", type=int, default=15)
    parser.add_argument("--exclude-title", action="append", default=[])
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--no-tech-dynamics", action="store_true")
    parser.add_argument("--tech-per-group", type=int, default=0)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    exclude_titles = DEFAULT_EXCLUDE_TITLES | set(args.exclude_title)
    clusters = [
        cluster
        for cluster in payload.get("clusters", [])
        if clean_text(cluster.get("primary_title")) not in exclude_titles
    ]
    display_clusters = visible_clusters(clusters, args.per_category)
    tech_groups: list[dict[str, Any]] = []
    if not args.no_tech_dynamics:
        raw_path = resolve_raw_items_path(payload, ROOT)
        if raw_path is not None:
            raw_items = json.loads(raw_path.read_text(encoding="utf-8"))
            tech_groups = build_tech_dynamics(
                raw_items,
                per_group=args.tech_per_group or None,
            )
    translations = build_translations(
        display_clusters + tech_translation_targets(tech_groups),
        args.translation_cache,
        disabled=args.no_translate,
    )

    output = args.output or args.input.with_name("scored_candidate_pool_by_category.html")
    output.write_text(
        render_html(payload, display_clusters, translations, args.per_category, tech_groups),
        encoding="utf-8",
    )
    print(f"html={output}")
    print(f"categories={len(set(category_label(cluster.get('primary_category')) for cluster in clusters))}")
    print(f"excluded={len(payload.get('clusters', [])) - len(clusters)}")
    print(f"translated_texts={sum(1 for value in translations.values() if value)}")
    print(f"tech_dynamics_items={sum(len(group['items']) for group in tech_groups)}")


def grouped_clusters(
    clusters: list[dict[str, Any]],
    per_category: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        grouped[category_label(cluster.get("primary_category"))].append(cluster)
    for items in grouped.values():
        items.sort(key=lambda item: float(item.get("ranking_score") or 0), reverse=True)
        del items[per_category:]
    return dict(sorted(grouped.items(), key=lambda item: category_sort_key(item[0])))


def category_sort_key(category: str) -> tuple[int, str]:
    try:
        return (CATEGORY_ORDER.index(category), category)
    except ValueError:
        return (len(CATEGORY_ORDER), category)


def visible_clusters(clusters: list[dict[str, Any]], per_category: int) -> list[dict[str, Any]]:
    grouped = grouped_clusters(clusters, per_category)
    return [cluster for items in grouped.values() for cluster in items]


def display_entries(
    grouped: dict[str, list[dict[str, Any]]],
    tech_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    used: set[str] = set()
    category_index = 1
    for category in CATEGORY_ORDER:
        if category in grouped:
            entries.append(
                {
                    "kind": "category",
                    "id": f"cat-{category_index}",
                    "label": category,
                    "count": len(grouped[category]),
                    "items": grouped[category],
                }
            )
            used.add(category)
            category_index += 1
        if category == TECH_AFTER_CATEGORY and tech_groups:
            entries.append(
                {
                    "kind": "tech",
                    "id": "tech-dynamics",
                    "label": TECH_DYNAMICS_TITLE,
                    "count": sum(len(group["items"]) for group in tech_groups),
                    "groups": tech_groups,
                }
            )
    for category, items in grouped.items():
        if category in used:
            continue
        entries.append(
            {
                "kind": "category",
                "id": f"cat-{category_index}",
                "label": category,
                "count": len(items),
                "items": items,
            }
        )
        category_index += 1
    return entries


def render_entry(entry: dict[str, Any], translations: dict[str, str]) -> str:
    if entry["kind"] == "tech":
        return render_tech_dynamics_html(entry["groups"], translations)
    return render_category_section(entry["id"], entry["label"], entry["items"], translations)


def render_html(
    payload: dict[str, Any],
    clusters: list[dict[str, Any]],
    translations: dict[str, str],
    per_category: int,
    tech_groups: list[dict[str, Any]],
) -> str:
    grouped = grouped_clusters(clusters, per_category)
    summary = payload.get("summary") or {}
    entries = display_entries(grouped, tech_groups)
    nav = "\n".join(
        f'<a href="#{escape(entry["id"])}">{escape(entry["label"])} <span>{entry["count"]}</span></a>'
        for entry in entries
    )
    sections = "\n".join(
        render_entry(entry, translations)
        for entry in entries
    )
    excluded_count = len(payload.get("clusters", [])) - len(clusters)
    stats = {
        "score_distribution": summary.get("score_distribution"),
        "normalized_category_distribution": summary.get("normalized_category_distribution"),
        "filtered_category_distribution": summary.get("filtered_category_distribution"),
        "event_cluster_distribution": summary.get("category_distribution"),
        "run_meta": payload.get("run_meta"),
    }
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(PAGE_TITLE)}</title>
  <style>
    :root {{
      --ink: #18211d;
      --muted: #69746e;
      --paper: #f6efe3;
      --card: rgba(255,255,250,.92);
      --line: rgba(26,36,31,.13);
      --green: #294f45;
      --copper: #b86f3f;
      --blue: #335d7e;
      --summary: #f0f6ef;
      --shadow: 0 22px 68px rgba(42,32,18,.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Noto Serif SC", "Songti SC", Georgia, serif;
      background:
        radial-gradient(circle at 8% 0%, rgba(184,111,63,.22), transparent 28rem),
        radial-gradient(circle at 88% 12%, rgba(41,79,69,.16), transparent 32rem),
        linear-gradient(135deg, #f8efe1, #eef4ef 54%, #f5efe9);
    }}
    header {{
      padding: 50px min(6vw, 78px) 24px;
      border-bottom: 1px solid var(--line);
    }}
    .eyebrow {{
      color: var(--green);
      font: 800 12px/1.2 "Trebuchet MS", sans-serif;
      letter-spacing: .16em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 10px 0 12px;
      max-width: 1040px;
      font-size: clamp(36px, 6vw, 74px);
      line-height: .95;
      letter-spacing: -.055em;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font: 14px/1.45 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .meta span, nav a {{
      display: inline-flex;
      gap: 6px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.58);
      border-radius: 999px;
      padding: 8px 11px;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 18px;
    }}
    nav a {{
      color: var(--ink);
      text-decoration: none;
      font: 800 13px/1.2 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    nav a:hover {{
      background: var(--green);
      color: #fffaf0;
    }}
    main {{
      padding: 34px min(6vw, 78px) 90px;
    }}
    section.category {{
      margin: 0 0 46px;
    }}
    .category-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 16px;
    }}
    h2 {{
      margin: 0;
      font-size: clamp(26px, 4vw, 46px);
      letter-spacing: -.045em;
    }}
    .category-count {{
      color: var(--muted);
      font: 800 13px/1.2 "Trebuchet MS", sans-serif;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 18px;
    }}
    .tech-dynamics {{
      margin: 0 0 48px;
      padding: 24px;
      border: 1px solid rgba(51,93,126,.18);
      border-radius: 30px;
      background: linear-gradient(135deg, rgba(255,255,250,.76), rgba(231,240,238,.72));
      box-shadow: var(--shadow);
    }}
    .tech-note {{
      max-width: 980px;
      color: var(--muted);
      font: 14px/1.7 "Trebuchet MS", "Noto Sans SC", sans-serif;
      margin: 8px 0 20px;
    }}
    .tech-group {{
      margin-top: 22px;
    }}
    .tech-group h3 {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 14px;
      margin: 0 0 12px;
      font-size: 22px;
    }}
    .tech-group-count {{
      color: var(--muted);
      font: 800 12px/1.2 "Trebuchet MS", sans-serif;
    }}
    .tech-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 13px;
    }}
    .tech-card {{
      border-radius: 20px;
      padding: 15px;
      background: rgba(255,255,255,.62);
      border: 1px solid var(--line);
      box-shadow: none;
    }}
    .tech-card h4 {{
      margin: 0 0 8px;
      font-size: 16px;
      line-height: 1.28;
    }}
    .tech-card .zh-title {{
      font-size: 14px;
      margin-bottom: 8px;
    }}
    .tech-card .zh-summary {{
      font-size: 13px;
      padding: 9px 10px;
      margin-bottom: 8px;
    }}
    .tech-meta {{
      color: var(--muted);
      font: 12px/1.45 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .read-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-top: 10px;
      border-radius: 999px;
      padding: 8px 12px;
      background: var(--green);
      color: #fffaf0;
      font: 900 12px/1.2 "Trebuchet MS", "Noto Sans SC", sans-serif;
      text-decoration: none;
      box-shadow: 0 10px 24px rgba(41,79,69,.18);
    }}
    .read-link:hover {{
      background: var(--copper);
    }}
    article {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 21px;
    }}
    .topline {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 12px;
    }}
    .rank {{
      width: 46px;
      height: 46px;
      border-radius: 16px;
      display: grid;
      place-items: center;
      color: #fffaf0;
      background: var(--green);
      font: 900 14px/1 "Trebuchet MS", sans-serif;
    }}
    .score {{
      text-align: right;
      color: var(--copper);
      font: 900 22px/1 "Trebuchet MS", sans-serif;
    }}
    .score small {{
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font: 12px/1.2 "Trebuchet MS", sans-serif;
    }}
    h3 {{
      margin: 0 0 9px;
      font-size: 21px;
      line-height: 1.2;
      letter-spacing: -.025em;
    }}
    a {{
      color: var(--ink);
      text-decoration-color: rgba(41,79,69,.45);
      text-underline-offset: 4px;
    }}
    p {{
      color: #38443f;
      font: 14px/1.66 "Trebuchet MS", "Noto Sans SC", sans-serif;
      margin: 0 0 10px;
    }}
    .zh-title {{
      color: #243b31;
      font: 700 16px/1.45 "Noto Sans SC", sans-serif;
      margin: 0 0 10px;
    }}
    .zh-summary {{
      margin: 10px 0 12px;
      padding: 12px 13px;
      background: var(--summary);
      border: 1px solid rgba(41,79,69,.14);
      border-radius: 16px;
      color: #263a30;
      font: 15px/1.62 "Noto Sans SC", sans-serif;
    }}
    .zh-summary span {{
      display: inline-flex;
      margin-right: 8px;
      color: var(--green);
      font-weight: 900;
    }}
    .original-summary {{
      color: var(--muted);
      font-size: 13px;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin: 13px 0;
      font: 12px/1.2 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .chip {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.62);
      border-radius: 999px;
      padding: 6px 8px;
      color: var(--muted);
    }}
    .chip.strong {{ color: var(--blue); font-weight: 900; }}
    details {{
      margin-top: 11px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    summary {{
      cursor: pointer;
      color: var(--green);
      font: 900 13px/1.2 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .related {{
      padding-left: 20px;
      margin: 9px 0 0;
    }}
    .related li {{
      margin: 9px 0;
      font: 13px/1.5 "Trebuchet MS", "Noto Sans SC", sans-serif;
    }}
    .related-zh {{
      color: #2f594c;
      margin-top: 3px;
    }}
    .secondary {{
      margin-top: 38px;
      opacity: .72;
    }}
    .secondary details {{
      background: rgba(255,255,250,.58);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 14px 16px;
    }}
    pre {{
      white-space: pre-wrap;
      font: 12px/1.55 Consolas, monospace;
      color: #47514c;
    }}
    @media (max-width: 760px) {{
      .cards {{ grid-template-columns: 1fr; }}
      article {{ border-radius: 22px; padding: 18px; }}
      .category-head {{ flex-direction: column; gap: 6px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Daily Newsletter Category Brief</div>
    <h1>{escape(PAGE_TITLE)}</h1>
    <div class="meta">
      <span>{escape(MAX_PER_CATEGORY)} {per_category} {escape(ITEM_UNIT)}</span>
      <span>{escape(CATEGORY)} {len(grouped)}</span>
      <span>{escape(DISPLAY)} {sum(len(items) for items in grouped.values())} {escape(ITEM_UNIT)}</span>
      <span>{escape(EXCLUDED)} {excluded_count} {escape(ITEM_UNIT)}</span>
      <span>Raw {summary.get("raw_item_count")}</span>
    </div>
    <nav>{nav}</nav>
  </header>
  <main>
    {sections}
    <section class="secondary">
      <details>
        <summary>{escape(MIDDLE_STATS)}</summary>
        <pre>{escape(json.dumps(stats, ensure_ascii=False, indent=2))}</pre>
      </details>
    </section>
  </main>
</body>
</html>
"""


def render_tech_dynamics_html(groups: list[dict[str, Any]], translations: dict[str, str]) -> str:
    group_html = "\n".join(render_tech_group_html(group, translations) for group in groups)
    return f"""<section class="tech-dynamics" id="tech-dynamics">
  <div class="eyebrow">Technology Signals</div>
  <h2>{escape(TECH_DYNAMICS_TITLE)}</h2>
  <p class="tech-note">{escape(TECH_DYNAMICS_NOTE)}</p>
  {group_html}
</section>"""


def render_tech_group_html(group: dict[str, Any], translations: dict[str, str]) -> str:
    cards = "\n".join(render_tech_card_html(index, item, translations) for index, item in enumerate(group["items"], start=1))
    return f"""<section class="tech-group">
  <h3>{escape(group["label"])}<span class="tech-group-count">{group["total"]} {escape(ITEMS_UNIT)}</span></h3>
  <div class="tech-grid">{cards}</div>
</section>"""


def render_tech_card_html(index: int, item: dict[str, Any], translations: dict[str, str]) -> str:
    title = item["title"]
    title_zh = item_title_zh(item, translations)
    summary_zh = item_summary_zh(item, translations)
    title_zh_html = (
        f'<p class="zh-title">{escape(ZH_TITLE_LABEL)}：{escape(title_zh)}</p>'
        if title_zh and title_zh != title
        else ""
    )
    meta = [f"{SOURCE_LABEL}={item['source_name']}"]
    if item.get("rank_position"):
        meta.append(f"{RANK_LABEL}={item['rank_position']}")
    if item.get("rank_section"):
        meta.append(f"section={item['rank_section']}")
    return f"""<article class="tech-card">
  <h4>{index}. <a href="{escape(item["url"])}" target="_blank" rel="noopener noreferrer">{escape(title)}</a></h4>
  {title_zh_html}
  <div class="zh-summary"><span>{escape(ZH_SUMMARY_LABEL)}</span>{escape(summary_zh)}</div>
  <div class="tech-meta">{escape(" · ".join(meta))}</div>
</article>"""


def render_category_section(
    category_index: int,
    category: str,
    items: list[dict[str, Any]],
    translations: dict[str, str],
) -> str:
    cards = "\n".join(render_card(index, item, translations) for index, item in enumerate(items, start=1))
    return f"""<section class="category" id="cat-{category_index}">
  <div class="category-head">
    <h2>{escape(category)}</h2>
    <div class="category-count">{len(items)} {escape(ITEM_UNIT)}</div>
  </div>
  <div class="cards">{cards}</div>
</section>"""


def render_card(index: int, item: dict[str, Any], translations: dict[str, str]) -> str:
    title = clean_text(item.get("primary_title"))
    title_zh = localized_title(item, translations)
    summary = clean_text(item.get("summary"))
    summary_zh = localized_summary(item, translations)
    url = clean_text(item.get("url"))
    source = clean_text(item.get("source_id"))
    rule = item.get("rule_score") or {}
    model = item.get("model_score") or {}
    related_items = item.get("related_reports") or []
    related = ""
    if related_items:
        related = f'<details open><summary>{escape(RELATED)} / {escape(CLUSTER_MEMBERS)}</summary><ul class="related">'
        for related_item in related_items:
            related_title = clean_text(related_item.get("title"))
            related_title_zh = localized_related_title(related_item, translations)
            related_url = clean_text(related_item.get("url"))
            related_zh = (
                f'<div class="related-zh">{escape(ZH_TITLE)}：{escape(related_title_zh)}</div>'
                if related_title_zh and related_title_zh != related_title
                else ""
            )
            related += (
                "<li>"
                f'<a href="{escape(related_url)}" target="_blank" rel="noopener noreferrer">{escape(related_title)}</a>'
                f"{related_zh}"
                f"<div>source={escape(clean_text(related_item.get('source_id')))}; "
                f"legacy_score={escape(str(related_item.get('score')))}</div>"
                "</li>"
            )
        related += "</ul></details>"

    title_zh_html = (
        f'<p class="zh-title">{escape(ZH_TITLE)}：{escape(title_zh)}</p>'
        if title_zh and title_zh != title
        else ""
    )
    original_summary = (
        f'<p class="original-summary">{escape(ORIGINAL_SUMMARY)}：{escape(summary)}</p>'
        if summary and summary != summary_zh
        else ""
    )
    return f"""<article>
  <div class="topline">
    <div class="rank">#{index}</div>
    <div class="score">{float(item.get("ranking_score") or 0):.2f}<small>{escape(RULE)} {float(rule.get("total") or 0):.2f} / {escape(MODEL)} {float(model.get("total") or 0):.2f}</small></div>
  </div>
  <h3><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(title)}</a></h3>
  {title_zh_html}
  <div class="zh-summary"><span>{escape(ZH_SUMMARY)}</span>{escape(summary_zh)}</div>
  {original_summary}
  <div class="chips">
    <span class="chip strong">source={escape(source)}</span>
    <span class="chip">related={escape(str(item.get("related_count") or 0))}</span>
    <span class="chip">model={escape(clean_text(model.get("mode")))}</span>
  </div>
  {related}
</article>"""


def render_tech_card_html(index: int, item: dict[str, Any], translations: dict[str, str]) -> str:
    title = item["title"]
    title_zh = item_title_zh(item, translations)
    summary_zh = item_summary_zh(item, translations)
    title_zh_html = (
        f'<p class="zh-title">{escape(ZH_TITLE_LABEL)}：{escape(title_zh)}</p>'
        if title_zh and title_zh != title
        else ""
    )
    meta = [f"{SOURCE_LABEL}={item['source_name']}"]
    if item.get("rank_position"):
        meta.append(f"{RANK_LABEL}={item['rank_position']}")
    if item.get("rank_section"):
        meta.append(f"section={item['rank_section']}")
    return f"""<article class="tech-card">
  <h4>{index}. <a href="{escape(item["url"])}" target="_blank" rel="noopener noreferrer">{escape(title)}</a></h4>
  {title_zh_html}
  <div class="zh-summary"><span>{escape(ZH_SUMMARY_LABEL)}</span>{escape(summary_zh)}</div>
  <div class="tech-meta">{escape(" · ".join(meta))}</div>
  <a class="read-link" href="{escape(item["url"])}" target="_blank" rel="noopener noreferrer">{escape(OPEN_ORIGINAL)}</a>
</article>"""


def render_category_section(
    section_id: str,
    category: str,
    items: list[dict[str, Any]],
    translations: dict[str, str],
) -> str:
    cards = "\n".join(render_card(index, item, translations) for index, item in enumerate(items, start=1))
    return f"""<section class="category" id="{escape(section_id)}">
  <div class="category-head">
    <h2>{escape(category)}</h2>
    <div class="category-count">{len(items)} {escape(ITEM_UNIT)}</div>
  </div>
  <div class="cards">{cards}</div>
</section>"""


def render_card(index: int, item: dict[str, Any], translations: dict[str, str]) -> str:
    title = clean_text(item.get("primary_title"))
    title_zh = localized_title(item, translations)
    summary = clean_text(item.get("summary"))
    summary_zh = localized_summary(item, translations)
    url = clean_text(item.get("url"))
    source = clean_text(item.get("source_id"))
    rule = item.get("rule_score") or {}
    model = item.get("model_score") or {}
    related_items = item.get("related_reports") or []
    related = ""
    if related_items:
        related = f'<details open><summary>{escape(RELATED)} / {escape(CLUSTER_MEMBERS)}</summary><ul class="related">'
        for related_item in related_items:
            related_title = clean_text(related_item.get("title"))
            related_title_zh = localized_related_title(related_item, translations)
            related_url = clean_text(related_item.get("url"))
            related_zh = (
                f'<div class="related-zh">{escape(ZH_TITLE)}：{escape(related_title_zh)}</div>'
                if related_title_zh and related_title_zh != related_title
                else ""
            )
            related += (
                "<li>"
                f'<a href="{escape(related_url)}" target="_blank" rel="noopener noreferrer">{escape(related_title)}</a>'
                f"{related_zh}"
                f"<div>source={escape(clean_text(related_item.get('source_id')))}; "
                f"legacy_score={escape(str(related_item.get('score')))}</div>"
                "</li>"
            )
        related += "</ul></details>"

    title_zh_html = (
        f'<p class="zh-title">{escape(ZH_TITLE)}：{escape(title_zh)}</p>'
        if title_zh and title_zh != title
        else ""
    )
    original_summary = (
        f'<p class="original-summary">{escape(ORIGINAL_SUMMARY)}：{escape(summary)}</p>'
        if summary and summary != summary_zh
        else ""
    )
    return f"""<article>
  <div class="topline">
    <div class="rank">#{index}</div>
    <div class="score">{float(item.get("ranking_score") or 0):.2f}<small>{escape(RULE)} {float(rule.get("total") or 0):.2f} / {escape(MODEL)} {float(model.get("total") or 0):.2f}</small></div>
  </div>
  <h3><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(title)}</a></h3>
  {title_zh_html}
  <div class="zh-summary"><span>{escape(ZH_SUMMARY)}</span>{escape(summary_zh)}</div>
  {original_summary}
  <div class="chips">
    <span class="chip strong">source={escape(source)}</span>
    <span class="chip">related={escape(str(item.get("related_count") or 0))}</span>
    <span class="chip">model={escape(clean_text(model.get("mode")))}</span>
  </div>
  <a class="read-link" href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(OPEN_ORIGINAL)}</a>
  {related}
</article>"""


if __name__ == "__main__":
    main()
