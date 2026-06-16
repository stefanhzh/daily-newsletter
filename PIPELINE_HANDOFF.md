# Daily Newsletter Pipeline Handoff

This document is for starting a new Codex chat to continue the `daily-newsletter` pipeline work, especially the next clustering step.

## Current Goal

Build an investor-oriented daily newsletter pipeline that:

- ingests news and trend items from source adapters,
- filters obvious noise,
- classifies items into seven boards,
- clusters related reports into events,
- scores event clusters,
- outputs a reviewable candidate pool and final newsletter.

The current development baseline should continue from the source adapters and the refactored pipeline discussed in the recent chat. Do not treat older exploratory folders as the active implementation.

## What To Use

Use these as the active project surface:

- `scripts/ingest/`: source adapters and shared ingestion primitives.
- `scripts/news_ingest.py`: source-ingest runner that outputs raw source results, HTML, and Markdown.
- `scripts/pipeline.py`: main pipeline orchestration. After the light refactor, it still owns normalization orchestration, clustering, scoring, selection, and rendering.
- `scripts/classification/`: extracted classification layer.
- `scripts/filters/`: extracted filtering layer.
- `config/`: source, scoring, threshold, classification, and noise configs.
- `reports/`: generated test outputs and regression baselines.

Ignore these as active pipeline code unless explicitly requested:

- `Agent-Reach/`
- `TrendRadar/`
- `xiaoyuzhou-mcp/`
- zip files and one-off recon artifacts

They are useful references or experiments, not the current daily-newsletter pipeline.

## Active Data Flow

Current flow:

```text
source adapters
  -> raw_items.json
  -> pipeline.load_items_from_path()
  -> normalize_ingested_items()
  -> filters.relevance.should_skip_ingested_item()
  -> filters.source_native_noise.should_drop_by_source_native_noise()
  -> classification.classifier.classify_raw_item()
  -> prefilter_items()
  -> score_items()
  -> cluster_items()
  -> apply_cluster_adjustments()
  -> select_items()
  -> render_candidate_pool() / render_newsletter()
```

Important field semantics:

- `section`: true source-native section only. If unavailable, use `""`.
- `source_tags`: source-native tags or topic labels, used as rule-matcher input.
- `rank_section`: ranking/list source, such as `homepage_top`, `news_homepage`, or `homepage_rank_proxy`.
- `rank_position`: position within that ranking/list source.
- `rank_section` is not a classification section.
- Adapters should not decide final newsletter category.

## Current Seven Boards

The pipeline uses these seven boards:

- 地缘政治
- 宏观经济
- 政策监管
- 产业趋势
- 科技进展
- 资本市场与交易
- 风险事件

## Light Refactor Status

The latest completed refactor split classification and filters out of `pipeline.py`.

New classification files:

- `scripts/classification/classifier.py`: classification entry point. Builds `ClassificationResult`.
- `scripts/classification/rule_matcher.py`: keyword scoring, short-token whole-word matching, strong rules, priority rules, tech-company routing.
- `scripts/classification/source_native.py`: reads and interprets `source_native_taxonomy_map.json`; currently mainly supports disabled sources and future native-section hard overrides.
- `scripts/classification/source_overrides.py`: reads source-specific classification strategy.
- `scripts/classification/explain.py`: placeholder helper for readable classification explanations.
- `scripts/classification/models.py`: small classification dataclass.

New filter files:

- `scripts/filters/relevance.py`: global title skip, source-specific skip, relevance gate.
- `scripts/filters/source_native_noise.py`: reads `source_native_noise_map.json` and applies drop/keep override rules.

New config files:

- `config/category_rules.json`: seven-board keyword rules, strong rules, priority rules, tech-company routing, secondary tag rules, source fallback buckets.
- `config/source_category_overrides.json`: AP/Axios/BBC source strategy metadata and source-specific score boosts.

Existing config files retained:

- `config/source_native_taxonomy_map.json`
- `config/source_native_noise_map.json`
- `config/sources.json`
- `config/scoring.json`
- `config/thresholds.json`
- `config/watchlists.json`

## What Was Migrated

Migrated from `pipeline.py`:

- `CATEGORY_KEYWORD_RULES`
- `_keyword_matches` short-token whole-word logic
- `_infer_primary_category`
- source-specific classification boosts
- tech-company / AI-company routing
- secondary tag inference
- global skip keywords
- source-specific skip keywords
- relevance gate
- source-native noise drop and keep override logic

Still intentionally inside `pipeline.py`:

- `CandidateItem`, `EventCluster`, `PipelineResult`
- load/config helpers
- normalize orchestration
- dimension and attribute inference
- prefilter against watchlists
- clustering
- scoring
- selection
- rendering

The next chat should focus on clustering before splitting scoring.

## Current Source Rules To Preserve

### AP

- `native_section_available=true`
- `rank_source=homepage_top`
- `homepage_rank_is_low_confidence=false`
- AP sports and entertainment native sections are dropped by `source_native_noise_map.json`, unless keep overrides apply.
- Google News is only enhancement/verification, not a hard filter.

Regression sample:

- `reports/source_ingest/ap-soft-google-trial-20260602/raw_items.json`

Expected regression:

- raw count: `16`
- filtered count after normalize: `14`
- cluster count: `13`
- category distribution:
  - 地缘政治: `8`
  - 资本市场与交易: `2`
  - 宏观经济: `1`
  - 政策监管: `3`

### Axios

- `native_section_available=false`
- `rank_source=homepage_rank_proxy`
- `local_url_is_not_section=true`
- `section=""`
- No inferred native section should be written.
- Classification falls back to seven-board rule matcher using title and summary.

Regression sample:

- `reports/source_ingest/axios-empty-section-check-20260602/raw_items.json`

Expected regression:

- raw count: `5`
- filtered count after normalize: `5`
- cluster count: `4`
- category distribution:
  - 政策监管: `3`
  - 地缘政治: `1`
  - 产业趋势: `1`

### BBC

- Uses public BBC News, Business, and Technology landing pages.
- `rank_section` is one of:
  - `news_homepage`
  - `business_homepage`
  - `technology_homepage`
- `section` comes from article page `page.subsection` or `page.section`.
- `source_tags` comes from article-end topic links.
- URL path is not treated as native section.
- Video/audio items are kept only if text summary or transcript-like text is available.
- BBC does not hard-map tags or sections to final category. It uses `title + summary + section + source_tags` as rule-matcher input.

Regression sample:

- `reports/source_ingest/bbc-homepage-tags-20260602-final/raw_items.json`

Expected regression:

- raw count: `20`
- filtered count after normalize: `20`
- cluster count: `20`
- category distribution:
  - 地缘政治: `11`
  - 风险事件: `1`
  - 政策监管: `3`
  - 资本市场与交易: `2`
  - 科技进展: `3`

## Verification Artifacts

Generated during the light refactor:

- `reports/pipeline-refactor-baseline-before.json`
- `reports/pipeline-refactor-baseline-after.json`
- `reports/pipeline-refactor-compare.json`
- `reports/pipeline-refactor-regression-candidate-pool.md`

The refactor preserved AP, Axios, and BBC results exactly for raw count, filtered count, cluster count, category distribution, and per-title category assignment.

Syntax and config validation were also run:

```powershell
@'
from pathlib import Path
import py_compile
files=[Path('daily-newsletter/scripts/pipeline.py')]
files.extend(Path('daily-newsletter/scripts/classification').glob('*.py'))
files.extend(Path('daily-newsletter/scripts/filters').glob('*.py'))
for path in files:
    py_compile.compile(str(path), doraise=True)
print("ok")
'@ | python -

python -m json.tool daily-newsletter\config\category_rules.json > $null
python -m json.tool daily-newsletter\config\source_category_overrides.json > $null
python -m json.tool daily-newsletter\config\source_native_noise_map.json > $null
python -m json.tool daily-newsletter\config\source_native_taxonomy_map.json > $null
```

## Recommended Next Chat Prompt

Use this when opening a new chat for clustering:

```text
Please continue daily-newsletter from PIPELINE_HANDOFF.md.

Focus only on the clustering layer. Do not change adapters or source ingest.
Current classification and filters have already been lightly refactored into scripts/classification and scripts/filters.

Goal:
- Improve event clustering so related reports are merged stably.
- Preserve AP/Axios/BBC classification/filter behavior.
- Use existing raw_items regression files and reports/pipeline-refactor-regression-candidate-pool.md as baseline.
- Do not split scoring yet unless necessary.

Please first inspect:
- daily-newsletter/PIPELINE_HANDOFF.md
- daily-newsletter/scripts/pipeline.py
- daily-newsletter/scripts/classification/
- daily-newsletter/scripts/filters/
- daily-newsletter/config/category_rules.json
- daily-newsletter/config/source_category_overrides.json
- daily-newsletter/reports/pipeline-refactor-baseline-before.json
- daily-newsletter/reports/pipeline-refactor-baseline-after.json

Then propose or implement a clustering-layer improvement with before/after statistics:
- raw count
- filtered count
- cluster count
- category distribution
- examples of merged clusters
- examples of false merges avoided
```

## Clustering Work Notes

Current clustering remains in `pipeline.py`.

Key functions:

- `cluster_items()`
- `_should_cluster()`
- `_event_anchor_tokens()`
- `_jaccard()`
- `_source_priority()`

Current clustering is deterministic and lightweight. It uses:

- same primary category requirement,
- time gap checks,
- token overlap / named-token anchors,
- source priority to pick primary item.

Likely next improvements:

- Separate clustering into `scripts/clustering/` only after understanding current behavior.
- Add a review export that shows why two items merged.
- Add a no-merge guard for broad anchors like `China`, `Trump`, `AI`, `market` unless another specific entity/action overlaps.
- Consider lightweight embedding only as optional later. For now, improve deterministic clustering first.

