# Daily Newsletter Release Manifest

## Goal

Publish a self-contained `daily-newsletter` project that can run the past-24-hour HTML/Markdown daily report in a new environment.

The repository should include code and non-secret configuration. It should not include generated reports, local caches, API keys, cookies, browser storage state, or private account sessions.

## Required Runtime Code

Top-level scripts used by the daily report:

```text
scripts/news_ingest.py
scripts/score_candidate_pool.py
scripts/pipeline.py
scripts/pipeline_models.py
scripts/localization.py
scripts/tech_dynamics.py
scripts/render_category_md.py
scripts/render_category_html.py
```

Runtime packages:

```text
scripts/ingest/
scripts/classification/
scripts/filters/
scripts/clustering/
scripts/scoring/
```

Why whole packages are included:

- `scripts/ingest/registry.py` imports every registered adapter at import time, so missing one adapter file can break the whole ingest CLI even if the source is not selected.
- `scripts/pipeline.py` imports classification, filters, clustering, and pipeline models.
- `scripts/score_candidate_pool.py` imports scoring modules.
- renderers import localization and technical-dynamics helpers.

## Required Config

These JSON files are loaded by the daily report runtime:

```text
config/source_presets.json
config/sources.json
config/scoring.json
config/thresholds.json
config/watchlists.json
config/category_rules.json
config/clustering_rules.json
config/source_category_overrides.json
config/source_native_taxonomy_map.json
config/source_native_noise_map.json
config/model_scoring_prompt.md
```

Useful companion YAML/reference configs:

```text
config/sources.yaml
config/scoring.yaml
config/thresholds.yaml
config/watchlists.yaml
```

Do not require or commit:

```text
config/auth_states/
config/*.storage_state.json
config/*.profile/
config/*token*
config/*cookie*
config/*session*
```

## Required Dependency Files

```text
requirements.txt
requirements-optional.txt
README-news-ingest.md
PIPELINE_HANDOFF.md
skills/daily-newsletter-report/
```

## Generated Or Local-Only Files To Exclude

```text
reports/
artifacts/
data/
experiments/
__pycache__/
*.pyc
.env
.env.*
*.key
*.pem
*.p12
*.pfx
*.sqlite
*.sqlite3
*.db
*.log
request_audit.jsonl
```

Model and translation caches should be regenerated per environment:

```text
reports/scoring/model_cache/
reports/scoring/translation_cache.json
```

## New Environment Secrets And Account State

Configure these outside the repo only when needed:

```text
DEEPSEEK_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_BASE_URL
DAILY_NEWSLETTER_AUTH_STATE_DIR
ZHIHU_HOT_STORAGE_STATE
XIAOHONGSHU_SEARCH_STORAGE_STATE
```

Optional adjacent project variables are documented in `environment.md`, but they are not required for the standard daily report.

## Publish Checklist

Before committing:

```powershell
git status --short
git check-ignore -v scripts\news_ingest.py config\sources.json skills\daily-newsletter-report\SKILL.md
python -m py_compile scripts\news_ingest.py scripts\score_candidate_pool.py scripts\render_category_md.py scripts\render_category_html.py
```

Before pushing to GitHub:

```powershell
git ls-files
```

Manually confirm `git ls-files` includes the required runtime code and config above, and excludes generated reports/secrets.

## New Repo Command

If the user confirms repository visibility:

```powershell
gh repo create stefanhzh/daily-newsletter --public --description "Investor-oriented daily news newsletter pipeline" --source . --remote origin
```

Use `--public` only after the user explicitly confirms the repository can be public. Otherwise use `--private`.
