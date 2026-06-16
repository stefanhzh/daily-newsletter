#!/usr/bin/env python3
"""Render scored candidate-pool JSON as a category-grouped Markdown brief."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import json
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

TITLE = zh(r"\u6309\u5206\u7c7b\u6574\u7406\u7684\u5019\u9009\u65b0\u95fb")
SUMMARY = zh(r"\u6458\u8981")
LOCALIZATION_NOTE = zh(
    r"\u4e2d\u6587\u6458\u8981\u683c\u5f0f\uff1a\u53c2\u8003 DailyBrief "
    r"\u7684\u65f6\u653f\u89c2\u5bdf\uff0c\u4f7f\u7528\u4e2d\u6027\u3001"
    r"\u4e8b\u5b9e\u578b\u3001\u4fe1\u606f\u5bc6\u5ea6\u8f83\u9ad8\u7684"
    r"\u4e2d\u6587\u6458\u8981\u3002"
)
ZH_TITLE = zh(r"\u4e2d\u6587\u6807\u9898")
ZH_SUMMARY = zh(r"\u4e2d\u6587\u6458\u8981")
RELATED_REPORTS = zh(r"\u76f8\u5173\u62a5\u9053")


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

    output = args.output or args.input.with_name("scored_candidate_pool_by_category.md")
    output.write_text(
        render_markdown(payload, display_clusters, translations, args.per_category, tech_groups),
        encoding="utf-8",
    )
    print(f"markdown={output}")
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


def render_markdown(
    payload: dict[str, Any],
    clusters: list[dict[str, Any]],
    translations: dict[str, str],
    per_category: int,
    tech_groups: list[dict[str, Any]],
) -> str:
    grouped = grouped_clusters(clusters, per_category)
    summary = payload.get("summary") or {}
    lines = [
        f"# {TITLE}",
        "",
        f"## {SUMMARY}",
        f"- Raw items: {summary.get('raw_item_count')}",
        f"- Event clusters before exclusion: {summary.get('cluster_count')}",
        f"- Display cap: top {per_category} per category",
        f"- Excluded items: {len(payload.get('clusters', [])) - len(clusters)}",
        f"- {LOCALIZATION_NOTE}",
        "",
    ]

    if tech_groups:
        lines.extend(render_tech_dynamics_markdown(tech_groups, translations))

    for category, items in grouped.items():
        lines.extend([f"## {category}", ""])
        for idx, item in enumerate(items, start=1):
            title = clean_text(item.get("primary_title"))
            title_zh = localized_title(item, translations)
            summary_zh = localized_summary(item, translations)
            url = clean_text(item.get("url"))
            rule = item.get("rule_score") or {}
            model = item.get("model_score") or {}
            lines.append(f"### {idx}. [{title}]({url})")
            if title_zh and title_zh != title:
                lines.append(f"- {ZH_TITLE}：{title_zh}")
            lines.append(f"- {ZH_SUMMARY}：{summary_zh}")
            lines.append(
                f"- Score: {float(item.get('ranking_score') or 0):.2f} = "
                f"rule {float(rule.get('total') or 0):.2f} + "
                f"model {float(model.get('total') or 0):.2f}"
            )
            lines.append(f"- Source: `{clean_text(item.get('source_id'))}`; related={item.get('related_count')}")

            related_items = item.get("related_reports") or []
            if related_items:
                lines.append(f"- Related reports / {RELATED_REPORTS}:")
                for related in related_items:
                    related_title = clean_text(related.get("title"))
                    related_title_zh = localized_related_title(related, translations)
                    related_url = clean_text(related.get("url"))
                    suffix = f"；{ZH_TITLE}：{related_title_zh}" if related_title_zh and related_title_zh != related_title else ""
                    lines.append(
                        f"  - [{related_title}]({related_url}){suffix}；"
                        f"source=`{clean_text(related.get('source_id'))}`"
                    )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_tech_dynamics_markdown(
    groups: list[dict[str, Any]],
    translations: dict[str, str],
) -> list[str]:
    lines = [
        f"## {TECH_DYNAMICS_TITLE}",
        "",
        f"- {TECH_DYNAMICS_NOTE}",
        "",
    ]
    for group in groups:
        lines.extend([f"### {group['label']}", f"- {group['total']} {ITEMS_UNIT}", ""])
        for idx, item in enumerate(group["items"], start=1):
            title = item["title"]
            title_zh = item_title_zh(item, translations)
            summary_zh = item_summary_zh(item, translations)
            lines.append(f"#### {idx}. [{title}]({item['url']})")
            if title_zh and title_zh != title:
                lines.append(f"- {ZH_TITLE_LABEL}：{title_zh}")
            lines.append(f"- {ZH_SUMMARY_LABEL}：{summary_zh}")
            meta = [f"{SOURCE_LABEL}=`{item['source_name']}`"]
            if item.get("rank_position"):
                meta.append(f"{RANK_LABEL}={item['rank_position']}")
            if item.get("rank_section"):
                meta.append(f"section=`{item['rank_section']}`")
            lines.append("- " + "; ".join(meta))
            lines.append("")
    return lines


def render_markdown(
    payload: dict[str, Any],
    clusters: list[dict[str, Any]],
    translations: dict[str, str],
    per_category: int,
    tech_groups: list[dict[str, Any]],
) -> str:
    grouped = grouped_clusters(clusters, per_category)
    summary = payload.get("summary") or {}
    lines = [
        f"# {TITLE}",
        "",
        f"## {SUMMARY}",
        f"- Raw items: {summary.get('raw_item_count')}",
        f"- Event clusters before exclusion: {summary.get('cluster_count')}",
        f"- Display cap: top {per_category} per category",
        f"- Excluded items: {len(payload.get('clusters', [])) - len(clusters)}",
        f"- {LOCALIZATION_NOTE}",
        "",
    ]

    emitted: set[str] = set()
    for category in CATEGORY_ORDER:
        if category in grouped:
            lines.extend(render_category_markdown(category, grouped[category], translations))
            emitted.add(category)
        if category == TECH_AFTER_CATEGORY and tech_groups:
            lines.extend(render_tech_dynamics_markdown(tech_groups, translations))

    for category, items in grouped.items():
        if category in emitted:
            continue
        lines.extend(render_category_markdown(category, items, translations))

    return "\n".join(lines).rstrip() + "\n"


def render_category_markdown(
    category: str,
    items: list[dict[str, Any]],
    translations: dict[str, str],
) -> list[str]:
    lines = [f"## {category}", ""]
    for idx, item in enumerate(items, start=1):
        title = clean_text(item.get("primary_title"))
        title_zh = localized_title(item, translations)
        summary_zh = localized_summary(item, translations)
        url = clean_text(item.get("url"))
        rule = item.get("rule_score") or {}
        model = item.get("model_score") or {}
        lines.append(f"### {idx}. [{title}]({url})")
        if title_zh and title_zh != title:
            lines.append(f"- {ZH_TITLE}：{title_zh}")
        lines.append(f"- {ZH_SUMMARY}：{summary_zh}")
        lines.append(
            f"- Score: {float(item.get('ranking_score') or 0):.2f} = "
            f"rule {float(rule.get('total') or 0):.2f} + "
            f"model {float(model.get('total') or 0):.2f}"
        )
        lines.append(f"- Source: `{clean_text(item.get('source_id'))}`; related={item.get('related_count')}")

        related_items = item.get("related_reports") or []
        if related_items:
            lines.append(f"- Related reports / {RELATED_REPORTS}:")
            for related in related_items:
                related_title = clean_text(related.get("title"))
                related_title_zh = localized_related_title(related, translations)
                related_url = clean_text(related.get("url"))
                suffix = (
                    f"（{ZH_TITLE}：{related_title_zh}）"
                    if related_title_zh and related_title_zh != related_title
                    else ""
                )
                lines.append(
                    f"  - [{related_title}]({related_url}){suffix}; "
                    f"source=`{clean_text(related.get('source_id'))}`"
                )
        lines.append("")
    return lines


def render_tech_dynamics_markdown(
    groups: list[dict[str, Any]],
    translations: dict[str, str],
) -> list[str]:
    lines = [
        f"## {TECH_DYNAMICS_TITLE}",
        "",
        f"- {TECH_DYNAMICS_NOTE}",
        "",
    ]
    for group in groups:
        lines.extend([f"### {group['label']}", f"- {group['total']} {ITEMS_UNIT}", ""])
        for idx, item in enumerate(group["items"], start=1):
            title = item["title"]
            title_zh = item_title_zh(item, translations)
            summary_zh = item_summary_zh(item, translations)
            lines.append(f"#### {idx}. [{title}]({item['url']})")
            if title_zh and title_zh != title:
                lines.append(f"- {ZH_TITLE_LABEL}：{title_zh}")
            lines.append(f"- {ZH_SUMMARY_LABEL}：{summary_zh}")
            meta = [f"{SOURCE_LABEL}=`{item['source_name']}`"]
            if item.get("rank_position"):
                meta.append(f"{RANK_LABEL}={item['rank_position']}")
            if item.get("rank_section"):
                meta.append(f"section=`{item['rank_section']}`")
            lines.append("- " + "; ".join(meta))
            lines.append("")
    return lines


if __name__ == "__main__":
    main()
