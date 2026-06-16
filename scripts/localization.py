from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


try:
    from deep_translator import GoogleTranslator
except Exception:  # noqa: BLE001
    GoogleTranslator = None


def zh(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


UNAVAILABLE_ZH = zh(r"\u4e2d\u6587\u6458\u8981\u6682\u4e0d\u53ef\u7528\u3002")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def english_heavy(text: str) -> bool:
    ascii_letters = len(re.findall(r"[A-Za-z]", text or ""))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    return ascii_letters >= 8 and ascii_letters > cjk


def load_translation_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_translation_cache(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_if_english(texts: list[str], value: Any) -> None:
    text = clean_text(value)
    if text and english_heavy(text) and text not in texts:
        texts.append(text)


def collect_cluster_texts(clusters: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for cluster in clusters:
        add_if_english(texts, cluster.get("primary_title", ""))
        add_if_english(texts, cluster.get("summary", ""))
        model_score = cluster.get("model_score") or {}
        add_if_english(texts, model_score.get("action_recommendation", ""))
        for related in cluster.get("related_reports") or []:
            add_if_english(texts, related.get("title", ""))
    return texts


def build_translations(
    clusters: list[dict[str, Any]],
    cache_path: Path,
    *,
    disabled: bool = False,
) -> dict[str, str]:
    """Populate a reusable text->Chinese cache for report rendering.

    This mirrors DailyBrief's useful boundary: localization is prepared before
    HTML/MD rendering and then treated as report data, not as browser-side work.
    """

    texts = collect_cluster_texts(clusters)
    cache = load_translation_cache(cache_path)

    if disabled or GoogleTranslator is None:
        for text in texts:
            cache.setdefault(text, "")
        save_translation_cache(cache_path, cache)
        return cache

    translator = GoogleTranslator(source="auto", target="zh-CN")
    changed = False
    for text in texts:
        if cache.get(text):
            continue
        try:
            cache[text] = translator.translate(text[:4500])
            changed = True
            time.sleep(0.08)
        except Exception:  # noqa: BLE001
            cache.setdefault(text, "")
    if changed:
        save_translation_cache(cache_path, cache)
    return cache


def localize_text(text: Any, translations: dict[str, str]) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    if english_heavy(cleaned):
        return clean_text(translations.get(cleaned)) or ""
    return cleaned


def localized_title(cluster: dict[str, Any], translations: dict[str, str]) -> str:
    return localize_text(cluster.get("primary_title"), translations)


def localized_summary(cluster: dict[str, Any], translations: dict[str, str]) -> str:
    summary_zh = localize_text(cluster.get("summary"), translations)
    if not summary_zh:
        title_zh = localized_title(cluster, translations)
        if title_zh:
            summary_zh = title_zh
    return polish_observation_summary(summary_zh)


def localized_related_title(related: dict[str, Any], translations: dict[str, str]) -> str:
    return localize_text(related.get("title"), translations)


def polish_observation_summary(text: str) -> str:
    """Keep summaries close to DailyBrief's politics/news observation style.

    The renderer should show one neutral, dense Chinese factual sentence or
    paragraph. We do light cleanup only; no new facts are invented here.
    """

    text = clean_text(text)
    if not text:
        return UNAVAILABLE_ZH
    text = text.replace("。.", "。").replace("..", ".")
    text = re.sub(r"\s+([，。；：、）])", r"\1", text)
    text = re.sub(r"([（])\s+", r"\1", text)
    return text


def category_label(value: Any) -> str:
    text = clean_text(value)
    # Repair known mojibake category names observed in old generated artifacts.
    repairs = {
        "\u934f\u626e\u7d2d\u93c0\u633e\u4e0d": zh(r"\u5730\u7f18\u653f\u6cbb"),
        "\u7481\u52ec\u6e70\u752f\u50a8\u6e80\u4e36\u5a06\u93c4?": zh(r"\u8d44\u672c\u5e02\u573a\u4e0e\u4ea4\u6613"),
        "\u7ee9\u621e\u59a7\u8fd8\u6d94": zh(r"\u79d1\u6280\u8fdb\u5c55"),
        "\u690b\u5e83\u6adb\u6d93\u4e8b\u6b22": zh(r"\u98ce\u9669\u4e8b\u4ef6"),
        "\u6d5c\u0442\u7b1f\u8d72\u5a0b\u52cd": zh(r"\u4ea7\u4e1a\u8d8b\u52bf"),
        "\u93c0\u8de8\u74e5\u76e9\u7bcd": zh(r"\u653f\u7b56\u76d1\u7ba1"),
        "\u701b\u5fda\u8ddd\u89c7\u7f01\u5fcc\u6d4e": zh(r"\u5b8f\u89c2\u7ecf\u6d4e"),
    }
    return repairs.get(text, text)
