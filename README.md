# daily-newsletter

Investor-oriented daily news newsletter pipeline. The project ingests multi-source news, classifies and filters candidates, clusters related stories, applies rule/model-style scoring, and renders a Chinese daily report in Markdown and HTML.

## What It Produces

- A 24-hour investor-focused daily newsletter.
- Category sections such as geopolitics, macro economy, industry trends, capital markets, technology progress, technical dynamics, policy regulation, and risk events.
- Chinese titles and summaries for English-language sources.
- Clickable source links and related-story context.
- Optional technical dynamics section inspired by DailyBrief-style AI/tech monitoring.

## Pipeline

1. Ingest sources from `config/sources.json` / `config/sources.yaml`.
2. Normalize raw source records into candidate items.
3. Apply classification and filtering rules.
4. Cluster related items into event-level groups.
5. Score candidates and clusters.
6. Render category-grouped Markdown and HTML reports under `reports/`.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-optional.txt
playwright install chromium
```

Run a 24-hour newsletter with heuristic scoring:

```powershell
python scripts\score_candidate_pool.py --all-sources --hours 24 --scoring-mode heuristic --with-classification --with-clustering --with-tech-dynamics --render-html
```

Render category Markdown or HTML from an existing scoring run:

```powershell
python scripts\render_category_md.py --input reports\scoring\<run-id>\scored_candidate_pool.json
python scripts\render_category_html.py --input reports\scoring\<run-id>\scored_candidate_pool_by_category.md
```

## Optional Model Scoring

The default development path can run without a model API by using heuristic scoring. For production-quality semantic scoring, configure a compatible model provider through environment variables and use the model scoring branch.

Create a local `.env` file or set variables in your shell:

```powershell
$env:OPENAI_API_KEY="..."
$env:DEEPSEEK_API_KEY="..."
```

Model prompts and schema-style guidance live in:

```text
config/model_scoring_prompt.md
```

Do not commit API keys, cookies, browser storage states, or generated report artifacts.

## Auth State And Local-Only Files

Some sources may require local browser login state or account-specific adapters. These are intentionally excluded from version control:

```text
.env
config/auth_states/
reports/
data/
artifacts/
*.storage_state.json
```

In a new environment, recreate those files locally after installing dependencies. If a source requires browser authentication, capture a fresh Playwright storage state on that machine rather than copying private login state into the repository.

## Main Configuration

- `config/sources.json` and `config/sources.yaml`: source registry.
- `config/source_presets.json`: source groups and presets.
- `config/category_rules.json`: classification/category rules.
- `config/clustering_rules.json`: clustering behavior.
- `config/scoring.json` and `config/scoring.yaml`: scoring weights and defaults.
- `config/thresholds.json` and `config/thresholds.yaml`: selection thresholds.
- `config/source_native_noise_map.json`: platform-specific noise suppression.
- `config/model_scoring_prompt.md`: optional semantic scoring prompt.

## Skill

The reusable Codex skill is included at:

```text
skills/daily-newsletter-report/
```

Use it as the operational playbook for running, validating, and rendering the full daily newsletter workflow.

## Repository Hygiene

This public repository should contain reusable code, configs, and documentation only. It should not contain:

- API keys or `.env` files.
- Browser auth state.
- Raw paid-source exports.
- Generated daily reports.
- Translation caches.
- Local experiments unrelated to the newsletter pipeline.
