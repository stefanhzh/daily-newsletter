from __future__ import annotations

import re
from typing import Any

from classification.rule_matcher import normalize_text
from clustering.models import ClusterDecision
from pipeline_models import CandidateItem


DEFAULT_CLUSTERING_RULES: dict[str, Any] = {
    "time_window_hours": 36,
    "token_stopwords": [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "same",
        "that",
        "the",
        "this",
        "to",
        "with",
    ],
    "generic_entity_tokens": [
        "breaking",
        "billion",
        "candidate",
        "candidates",
        "ceo",
        "center",
        "company",
        "daily",
        "data",
        "dem",
        "dems",
        "democrat",
        "democrats",
        "early",
        "election",
        "elections",
        "estimates",
        "exclusive",
        "goal",
        "gov",
        "government",
        "hit",
        "house",
        "leader",
        "leaders",
        "latest",
        "live",
        "market",
        "markets",
        "may",
        "million",
        "minister",
        "minority",
        "news",
        "open",
        "official",
        "officials",
        "president",
        "primary",
        "prime",
        "raises",
        "report",
        "reports",
        "republican",
        "republicans",
        "revenue",
        "says",
        "senate",
        "source",
        "sources",
        "state",
        "states",
        "this",
        "update",
        "updates",
        "why",
    ],
    "generic_roundup_title_patterns": [
        "daily open",
        "live updates",
        "morning bid",
        "startup battlefield",
        "the exchange",
        "top stories",
        "what to watch",
    ],
    "event_action_families": {
        "attack": ["attack", "attacks", "attacked", "strike", "strikes", "hit", "hits", "missile", "bomb", "bombs"],
        "ceasefire": ["ceasefire", "truce", "halt"],
        "financing": ["raise", "raises", "raised", "seeks", "seek", "fund", "funding", "sale", "sales"],
        "formation": ["form", "forms", "forming", "secures", "secured", "term"],
        "investigation": ["probe", "probes", "investigate", "investigation", "lawsuit", "sue", "sues", "sued"],
        "launch": ["launch", "launches", "launched", "release", "releases", "rollout"],
        "listing": ["ipo", "listing", "list", "lists", "file", "files", "filing"],
        "policy": ["approve", "approves", "block", "blocks", "blocked", "ban", "bans", "tariff", "sanction", "sanctions"],
    },
    "event_anchor_terms": [
        "ai",
        "boj",
        "china",
        "cornyn",
        "ecb",
        "fed",
        "gaza",
        "gold",
        "india",
        "inflation",
        "iran",
        "israel",
        "ipo",
        "japan",
        "market",
        "markets",
        "metals",
        "oil",
        "paxton",
        "pboc",
        "power",
        "profits",
        "rba",
        "rbi",
        "rbnz",
        "russia",
        "sanctions",
        "tariff",
        "trump",
        "ukraine",
    ],
    "broad_event_anchors": [
        "ai",
        "china",
        "democrats",
        "fed",
        "iran",
        "israel",
        "japan",
        "market",
        "markets",
        "republicans",
        "russia",
        "trump",
        "ukraine",
        "war",
    ],
    "shared_action_terms": [
        "acquisition",
        "ceasefire",
        "deal",
        "election",
        "files",
        "ipo",
        "launch",
        "launches",
        "lawsuit",
        "merger",
        "probe",
        "sanction",
        "sanctions",
        "strike",
        "strikes",
        "sues",
        "tariff",
    ],
    "thresholds": {
        "distinct_anchor_similarity_min": 0.55,
        "broad_anchor_similarity_min": 0.2,
        "generic_roundup_similarity_min": 0.45,
        "meaningful_anchor_low_similarity_action_required_below": 0.18,
        "meaningful_anchor_min_count": 2,
        "meaningful_anchor_shared_token_min_count": 3,
        "meaningful_anchor_time_window_hours": 24,
        "high_token_similarity": 0.6,
        "shared_tokens_recent_min_count": 5,
        "shared_tokens_recent_similarity": 0.25,
        "shared_tokens_recent_time_window_hours": 12,
        "entity_overlap_min_count": 2,
        "entity_overlap_similarity": 0.28,
        "entity_similarity_min_count": 1,
        "entity_similarity_overlap_similarity": 0.42,
        "entities_and_recent_tokens_min_count": 2,
        "entities_and_recent_tokens_shared_token_min_count": 5,
        "entities_and_recent_tokens_similarity": 0.2,
        "entities_and_recent_tokens_time_window_hours": 12,
        "same_source_family_similarity": 0.5,
    },
    "confidence": {
        "meaningful_anchor_base": 0.62,
        "meaningful_anchor_per_anchor": 0.04,
        "meaningful_anchor_cap": 0.92,
        "shared_tokens_recent_base": 0.48,
        "shared_tokens_recent_per_token": 0.025,
        "shared_tokens_recent_cap": 0.86,
        "entity_overlap_base": 0.55,
        "entity_overlap_per_entity": 0.04,
        "entity_overlap_cap": 0.9,
        "entity_similarity_base": 0.52,
        "entity_similarity_per_entity": 0.04,
        "entity_similarity_cap": 0.86,
        "entities_and_recent_tokens_base": 0.5,
        "entities_and_recent_tokens_per_entity": 0.04,
        "entities_and_recent_tokens_cap": 0.84,
    },
}


def clustering_rules(configs: dict[str, Any]) -> dict[str, Any]:
    configured = configs.get("clustering_rules") or {}
    merged = dict(DEFAULT_CLUSTERING_RULES)
    merged.update(configured)
    merged["thresholds"] = {
        **DEFAULT_CLUSTERING_RULES["thresholds"],
        **configured.get("thresholds", {}),
    }
    merged["confidence"] = {
        **DEFAULT_CLUSTERING_RULES["confidence"],
        **configured.get("confidence", {}),
    }
    return merged


def normalize_for_cluster(text: str) -> str:
    return normalize_text(text)


def tokenize(text: str, rules: dict[str, Any]) -> set[str]:
    stopwords = set(rules["token_stopwords"])
    normalized = normalize_for_cluster(text)
    return {
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in stopwords
    }


def ordered_tokens(text: str, rules: dict[str, Any]) -> list[str]:
    stopwords = set(rules["token_stopwords"])
    normalized = normalize_for_cluster(text)
    tokens: list[str] = []
    seen: set[str] = set()
    for token in normalized.split():
        if len(token) < 2 or token in stopwords or token in seen:
            continue
        tokens.append(token)
        seen.add(token)
    return tokens


def slugify_event_key(text: str, rules: dict[str, Any]) -> str:
    tokens = ordered_tokens(text, rules)
    return "-".join(tokens[:6]) or "misc-event"


def extract_named_tokens(item: CandidateItem, rules: dict[str, Any]) -> set[str]:
    text = f"{item.title} {item.summary}"
    ascii_entities = set(re.findall(r"\b[A-Z][A-Za-z0-9&\.-]{1,}\b", text))
    acronyms = set(re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b", text))
    normalized_entities = {normalize_for_cluster(token) for token in ascii_entities | acronyms}
    generic_entities = set(rules["token_stopwords"]) | set(rules["generic_entity_tokens"])
    return {
        token
        for token in normalized_entities
        if token and token not in generic_entities
    }


def event_anchor_tokens(item: CandidateItem, rules: dict[str, Any]) -> set[str]:
    tokens = tokenize(f"{item.title} {item.summary}", rules)
    anchors = {token for token in tokens if token in set(rules["event_anchor_terms"])}
    anchors.update(token for token in extract_named_tokens(item, rules) if len(token) >= 3)
    return anchors


def action_families(item: CandidateItem, rules: dict[str, Any]) -> set[str]:
    title_tokens = tokenize(item.title, rules)
    families: set[str] = set()
    for family, terms in rules.get("event_action_families", {}).items():
        if title_tokens & set(terms):
            families.add(str(family))
    return families


def shared_action_families(left: CandidateItem, right: CandidateItem, rules: dict[str, Any]) -> set[str]:
    return action_families(left, rules) & action_families(right, rules)


def is_generic_roundup_title(item: CandidateItem, rules: dict[str, Any]) -> bool:
    title = normalize_for_cluster(item.title)
    return any(pattern in title for pattern in rules.get("generic_roundup_title_patterns", []))


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def source_priority(
    item: CandidateItem,
    source_index: dict[str, dict[str, Any]],
) -> tuple[int, int, int, int]:
    source_meta = source_index.get(item.source_id, {})
    group_priority = {
        "regulator": 6,
        "exchange": 6,
        "official": 5,
        "wire": 4,
        "media": 3,
        "social": 2,
        "kol": 1,
    }
    tier_priority = {
        "T1": 3,
        "T1_5": 2,
        "T2": 1,
    }
    return (
        group_priority.get(source_meta.get("group", "media"), 0),
        tier_priority.get(source_meta.get("tier", "T2"), 0),
        item.final_score,
        -item.published_hours_ago,
    )


def same_event_decision(
    left: CandidateItem,
    right: CandidateItem,
    source_index: dict[str, dict[str, Any]],
    rules: dict[str, Any],
) -> ClusterDecision:
    thresholds = rules["thresholds"]
    confidence = rules["confidence"]
    if left.primary_category != right.primary_category:
        return ClusterDecision(False, "different_category", 0.0)

    hour_gap = abs(left.published_hours_ago - right.published_hours_ago)
    if hour_gap > int(rules["time_window_hours"]):
        return ClusterDecision(False, "outside_time_window", 0.0)

    if left.event_key and right.event_key and left.event_key == right.event_key:
        return ClusterDecision(True, "same_event_key", 1.0)

    left_tokens = tokenize(f"{left.title} {left.summary}", rules)
    right_tokens = tokenize(f"{right.title} {right.summary}", rules)
    token_similarity = jaccard(left_tokens, right_tokens)
    shared_tokens = left_tokens & right_tokens

    left_entities = extract_named_tokens(left, rules)
    right_entities = extract_named_tokens(right, rules)
    entity_overlap = len(left_entities & right_entities)
    left_anchors = event_anchor_tokens(left, rules)
    right_anchors = event_anchor_tokens(right, rules)
    anchor_overlap = len(left_anchors & right_anchors)
    action_overlap = shared_action_families(left, right, rules)

    left_source_group = source_index.get(left.source_id, {}).get("group")
    right_source_group = source_index.get(right.source_id, {}).get("group")
    same_source_family_bias = left_source_group == right_source_group
    same_source = left.source_id == right.source_id

    if (
        same_source
        and (is_generic_roundup_title(left, rules) or is_generic_roundup_title(right, rules))
        and token_similarity < float(thresholds["generic_roundup_similarity_min"])
    ):
        return ClusterDecision(False, "generic_roundup_guard", 0.0)

    if (
        left_anchors
        and right_anchors
        and anchor_overlap == 0
        and token_similarity < float(thresholds["distinct_anchor_similarity_min"])
    ):
        return ClusterDecision(False, "distinct_anchor_sets", 0.0)
    if left_anchors and right_anchors and anchor_overlap > 0:
        overlapping_anchors = left_anchors & right_anchors
        shared_action_terms = set(rules["shared_action_terms"]) & shared_tokens
        broad_anchors = set(rules["broad_event_anchors"])
        if (
            overlapping_anchors <= broad_anchors
            and token_similarity < float(thresholds["broad_anchor_similarity_min"])
            and not shared_action_terms
        ):
            return ClusterDecision(False, "broad_anchor_only", 0.0)
        meaningful_anchor_overlap = overlapping_anchors - broad_anchors
        if (
            len(meaningful_anchor_overlap) >= int(thresholds["meaningful_anchor_min_count"])
            and len(shared_tokens) >= int(thresholds["meaningful_anchor_shared_token_min_count"])
            and hour_gap <= int(thresholds["meaningful_anchor_time_window_hours"])
        ):
            if (
                token_similarity < float(thresholds["meaningful_anchor_low_similarity_action_required_below"])
                and not action_overlap
            ):
                return ClusterDecision(False, "meaningful_anchor_without_action", 0.0)
            score = min(
                float(confidence["meaningful_anchor_cap"]),
                float(confidence["meaningful_anchor_base"])
                + token_similarity
                + len(meaningful_anchor_overlap) * float(confidence["meaningful_anchor_per_anchor"]),
            )
            return ClusterDecision(True, "meaningful_anchor_overlap", round(score, 3))

    if token_similarity >= float(thresholds["high_token_similarity"]):
        return ClusterDecision(True, "high_token_similarity", round(token_similarity, 3))
    if (
        len(shared_tokens) >= int(thresholds["shared_tokens_recent_min_count"])
        and token_similarity >= float(thresholds["shared_tokens_recent_similarity"])
        and hour_gap <= int(thresholds["shared_tokens_recent_time_window_hours"])
    ):
        score = min(
            float(confidence["shared_tokens_recent_cap"]),
            float(confidence["shared_tokens_recent_base"])
            + token_similarity
            + len(shared_tokens) * float(confidence["shared_tokens_recent_per_token"]),
        )
        return ClusterDecision(True, "shared_tokens_recent", round(score, 3))
    if (
        entity_overlap >= int(thresholds["entity_overlap_min_count"])
        and token_similarity >= float(thresholds["entity_overlap_similarity"])
    ):
        score = min(
            float(confidence["entity_overlap_cap"]),
            float(confidence["entity_overlap_base"])
            + token_similarity
            + entity_overlap * float(confidence["entity_overlap_per_entity"]),
        )
        return ClusterDecision(True, "entity_overlap", round(score, 3))
    if (
        entity_overlap >= int(thresholds["entity_similarity_min_count"])
        and token_similarity >= float(thresholds["entity_similarity_overlap_similarity"])
    ):
        score = min(
            float(confidence["entity_similarity_cap"]),
            float(confidence["entity_similarity_base"])
            + token_similarity
            + entity_overlap * float(confidence["entity_similarity_per_entity"]),
        )
        return ClusterDecision(True, "entity_similarity_overlap", round(score, 3))
    if (
        entity_overlap >= int(thresholds["entities_and_recent_tokens_min_count"])
        and len(shared_tokens) >= int(thresholds["entities_and_recent_tokens_shared_token_min_count"])
        and token_similarity >= float(thresholds["entities_and_recent_tokens_similarity"])
        and hour_gap <= int(thresholds["entities_and_recent_tokens_time_window_hours"])
    ):
        score = min(
            float(confidence["entities_and_recent_tokens_cap"]),
            float(confidence["entities_and_recent_tokens_base"])
            + token_similarity
            + entity_overlap * float(confidence["entities_and_recent_tokens_per_entity"]),
        )
        return ClusterDecision(True, "entities_and_recent_tokens", round(score, 3))
    if same_source_family_bias and token_similarity >= float(thresholds["same_source_family_similarity"]):
        return ClusterDecision(True, "same_source_family_similarity", round(token_similarity, 3))
    return ClusterDecision(False, "insufficient_overlap", 0.0)


def generate_cluster_key(primary: CandidateItem, members: list[CandidateItem], rules: dict[str, Any]) -> str:
    if primary.event_key:
        return primary.event_key
    token_pool: list[str] = []
    for member in members:
        token_pool.extend(sorted(tokenize(member.title, rules))[:4])
    compact = "-".join(token_pool[:6]) or primary.id
    return f"cluster-{compact}"
