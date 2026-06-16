from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
from pipeline_models import EventCluster

from .models import ModelScore, RawItemMeta
from .rule_score import raw_meta_for_item, scoring_cache_key


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def score_cluster_with_model(
    cluster: EventCluster,
    *,
    prompt_path: Path,
    raw_meta_index: dict[tuple[str, str], RawItemMeta],
    cache_dir: Path,
    model: str | None = None,
    mode: str = "llm",
) -> ModelScore:
    if mode == "heuristic":
        return heuristic_model_score(cluster)
    if mode != "llm":
        raise ValueError(f"Unsupported model mode: {mode}")

    client_config = _client_config(model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{scoring_cache_key(cluster)}-{client_config['model']}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return _model_score_from_payload(cached, mode=f"{client_config['provider']}_cached")

    prompt = prompt_path.read_text(encoding="utf-8")
    user_payload = _model_user_payload(cluster, raw_meta_index)
    client = OpenAI(api_key=client_config["api_key"], base_url=client_config.get("base_url"))
    response = client.chat.completions.create(
        model=client_config["model"],
        messages=[
            {"role": "system", "content": _json_prompt(prompt)},
            {"role": "user", "content": user_payload},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw_text = response.choices[0].message.content or "{}"
    payload = json.loads(raw_text)
    payload["raw_response"] = raw_text
    payload["provider"] = client_config["provider"]
    payload["model"] = client_config["model"]
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _model_score_from_payload(payload, mode=client_config["provider"])


def heuristic_model_score(cluster: EventCluster) -> ModelScore:
    text = f"{cluster.primary_item.title} {cluster.primary_item.summary}".lower()
    score_1_to_5 = 2.4
    category = cluster.primary_item.primary_category
    category_label = _repair_category(category)
    if category_label in {"地缘政治", "宏观经济", "政策监管", "资本市场与交易", "风险事件"}:
        score_1_to_5 += 0.6
    if any(
        token in text
        for token in [
            "fed",
            "central bank",
            "tariff",
            "sanction",
            "oil",
            "ipo",
            "merger",
            "acquisition",
            "ai",
            "chip",
            "credit",
            "default",
        ]
    ):
        score_1_to_5 += 0.7
    if any(token in text for token in ["opinion", "commentary", "newsletter", "celebrity", "sports"]):
        score_1_to_5 -= 0.8
    if cluster.related_items:
        score_1_to_5 += min(0.4, len(cluster.related_items) * 0.15)
    score_1_to_5 = max(1.0, min(5.0, score_1_to_5))
    return ModelScore(
        total=round(score_1_to_5 * 10, 2),
        relevance_score_1_to_5=round(score_1_to_5, 2),
        expert_views=[
            {
                "expert": "heuristic",
                "group": "local fallback",
                "comment": "Local non-LLM fallback used because real model scoring was not requested or API credentials were unavailable.",
            }
        ],
        action_recommendation="Use only as a pipeline smoke test; rerun with --model-mode llm for editorial ranking.",
        mode="heuristic",
    )


def _client_config(model: str | None) -> dict[str, str | None]:
    requested_model = model or os.environ.get("NEWSLETTER_MODEL") or ""
    wants_deepseek = requested_model.startswith("deepseek") or bool(os.environ.get("DEEPSEEK_API_KEY"))
    if wants_deepseek:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set; cannot run DeepSeek model scoring.")
        return {
            "provider": "deepseek",
            "api_key": api_key,
            "base_url": os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL,
            "model": requested_model or DEFAULT_DEEPSEEK_MODEL,
        }

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot run OpenAI model scoring.")
    return {
        "provider": "openai",
        "api_key": api_key,
        "base_url": os.environ.get("OPENAI_BASE_URL"),
        "model": requested_model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
    }


def _json_prompt(prompt: str) -> str:
    return (
        prompt
        + "\n\nReturn only valid JSON with keys: "
        + "relevance_score_1_to_5, expert_views, action_recommendation. "
        + "The relevance score must be a number from 1 to 5. "
        + "Do not include Markdown fences or extra commentary."
    )


def _model_user_payload(
    cluster: EventCluster,
    raw_meta_index: dict[tuple[str, str], RawItemMeta],
) -> str:
    primary = cluster.primary_item
    primary_meta = raw_meta_for_item(primary, raw_meta_index)
    related = []
    for item in cluster.related_items[:5]:
        meta = raw_meta_for_item(item, raw_meta_index)
        related.append(
            {
                "title": item.title,
                "summary": item.summary,
                "source_id": item.source_id,
                "rank_section": meta.rank_section,
                "rank_position": meta.rank_position,
            }
        )
    payload = {
        "instruction": "Score semantic usefulness only. Do not decide final ranking; code will compute the final score.",
        "primary_news": {
            "title": primary.title,
            "summary": primary.summary,
            "category": primary.primary_category,
            "source_id": primary.source_id,
            "rank_section": primary_meta.rank_section,
            "rank_position": primary_meta.rank_position,
            "source_tags": primary_meta.source_tags,
        },
        "related_reports": related,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _model_score_from_payload(payload: dict[str, Any], *, mode: str) -> ModelScore:
    relevance = float(payload["relevance_score_1_to_5"])
    relevance = max(1.0, min(5.0, relevance))
    expert_views = payload.get("expert_views") or []
    if not isinstance(expert_views, list):
        expert_views = []
    return ModelScore(
        total=round(relevance * 10, 2),
        relevance_score_1_to_5=round(relevance, 2),
        expert_views=expert_views,
        action_recommendation=str(payload.get("action_recommendation") or ""),
        mode=mode,
        raw_response=str(payload.get("raw_response") or ""),
    )


def _repair_category(value: str) -> str:
    repairs = {
        "鍦扮紭鏀挎不": "地缘政治",
        "瀹忚缁忔祹": "宏观经济",
        "鏀跨瓥鐩戠": "政策监管",
        "浜т笟瓒嬪娍": "产业趋势",
        "绉戞妧杩涘睍": "科技进展",
        "璧勬湰甯傚満涓庝氦鏄?": "资本市场与交易",
        "椋庨櫓浜嬩欢": "风险事件",
    }
    return repairs.get(value, value)
