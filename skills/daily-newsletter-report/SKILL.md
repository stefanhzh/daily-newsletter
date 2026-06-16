---
name: daily-newsletter-report
description: Run the daily-newsletter project end-to-end into a Chinese investor-oriented news daily. Use when the user asks to generate, rerun, debug, validate, or explain the past-24-hour newsletter, HTML/Markdown daily report, source ingest, classification/filtering/clustering/scoring pipeline, technical-dynamics section, translation/localization, or report output quality.
---

# Daily Newsletter Report

## Purpose

Use this skill to operate the active `daily-newsletter` pipeline with the newsletter as the final artifact. The default output is a Chinese investor-oriented daily report grouped by category, with HTML and Markdown files.

Do not treat `Agent-Reach`, `TrendRadar`, `xiaoyuzhou-mcp`, or other exploration folders as the active pipeline.

## Default Workflow

Run commands from the repository root:

```powershell
python scripts\news_ingest.py --preset default --lookback-hours 24 --source-timeout 45 --jobs 4 --output-dir reports\source_ingest\all-sources-24h-YYYYMMDD
python scripts\score_candidate_pool.py --input reports\source_ingest\all-sources-24h-YYYYMMDD\raw_items.json --model-mode heuristic
python scripts\render_category_md.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 15
python scripts\render_category_html.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 15
```

Then copy the final user-facing files:

```powershell
Copy-Item reports\scoring\RUN_ID\scored_candidate_pool_by_category.md reports\scoring\RUN_ID\daily_newsletter_24h_YYYYMMDD.md -Force
Copy-Item reports\scoring\RUN_ID\scored_candidate_pool_by_category.html reports\scoring\RUN_ID\daily_newsletter_24h_YYYYMMDD.html -Force
```

Replace `YYYYMMDD` with the local date and `RUN_ID` with the scoring output directory printed by `score_candidate_pool.py`.

## Model Scoring

Use `--model-mode heuristic` for local development, smoke tests, and routine Codex runs where no API key should be consumed.

Use real LLM scoring only when the user explicitly wants it or has configured a safe environment variable:

```powershell
$env:DEEPSEEK_API_KEY="..."
python scripts\score_candidate_pool.py --input reports\source_ingest\...\raw_items.json --model-mode llm --model deepseek-chat --limit-model-calls 30
```

Never write API keys into code, reports, cache files, or skill files. If a key appears in chat, recommend rotating it before production use.

## Required QA

After rendering, verify:

- HTML and Markdown files exist.
- Navigation order is: `地缘政治`, `宏观经济`, `产业趋势`, `资本市场与交易`, `科技进展`, `技术动态`, `政策监管`, `风险事件`.
- Main news clusters do not contain `tiktok-profile-signals`, `github-trending`, or `github-issues-trends`.
- GitHub items still appear in `技术动态`.
- AP photo-caption items such as `(AP Photo/...)` do not appear.
- Source gaps from `source_summary.json` are reported honestly.
- Final response includes links to both HTML and Markdown outputs plus raw/filtered/cluster counts.

## Output Rules

- The final answer to the user should be concise and in Chinese.
- Provide absolute clickable paths to the generated HTML and Markdown.
- Mention whether scoring used `heuristic` or `llm`.
- Mention important source failures or timeouts, especially major sources such as CNBC, Nikkei Asia, A16Z, or Caixin.
- Do not overwhelm the user with internal logs unless asked.

## When More Detail Is Needed

Read [references/full-workflow.md](references/full-workflow.md) when you need implementation details, troubleshooting steps, validation snippets, category policy, source behavior, scoring design, or guidance for adapting the workflow.

Read [references/environment.md](references/environment.md) before porting the skill/project to a new machine, publishing the repository, debugging adapter/provider connectivity, or configuring authenticated/optional sources.

Read [references/release-manifest.md](references/release-manifest.md) before committing or publishing the project so the repository includes all daily-newsletter runtime code/config but excludes secrets, sessions, reports, and local caches.
