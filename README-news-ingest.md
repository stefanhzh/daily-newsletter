# News Ingest Console

News Ingest Console is a local source-fetching tool for team members and their local agents.
It reuses the adapters in `scripts/ingest/`, applies per-source limits from presets or user instructions, and renders a static HTML preview report.

## What It Does

- Fetches news, RSS, homepage ranked lists, hot lists, trend lists, blogs, and social/trend sources.
- Preserves `rank_position` when a source exposes homepage order, hot-list order, or trend ranking.
- Uses feed/API time order when a source has no stable public rank surface.
- Outputs machine-readable JSON plus human-readable HTML and Markdown preview reports.
- Runs locally on each teammate's computer with their own network, cookies, login state, and environment variables.

## Install

From the project root:

```bash
python -m pip install -r requirements.txt
```

If you need browser-auth based sources such as Xiaohongshu capture/recon flows, install Playwright browsers:

```bash
python -m playwright install chromium
```

Most lightweight RSS/API/page adapters do not need browser automation.

## Quick Start

Run the default preset:

```bash
python scripts/news_ingest.py
```

The default preset means: if the user gives only a general instruction such as "run source ingest" and does not specify platforms or counts, use `config/source_presets.json` preset `default`.

Outputs:

```text
reports/source_ingest/<timestamp>/
  raw_items.json
  source_summary.json
  index.html
  report.md
```

Open the generated HTML automatically:

```bash
python scripts/news_ingest.py --open
```

## Presets

Presets live in:

```text
config/source_presets.json
```

Current presets:

- `default`: all currently registered source adapters, excluding duplicate aliases.
- `investor-core`: focused investor-oriented scan, the earlier smaller 13-source set.
- `global-news`: global wire and major media sources.
- `tech-ai`: AI and technology sources.
- `china-market`: China market and policy sources.

Run a specific preset:

```bash
python scripts/news_ingest.py --preset investor-core
```

## Manual Source Selection

If the user specifies platforms and counts, manual source specs override the preset:

```bash
python scripts/news_ingest.py --sources reuters:20 bbc:10 caixin:15 techcrunch:10
```

Format:

```text
source_id:limit
```

If no limit is provided, the fallback limit is 20:

```bash
python scripts/news_ingest.py --sources reuters bbc
```

## List Available Sources

```bash
python scripts/news_ingest.py --list-sources
```

## Output Meaning

Each item includes fields such as:

```text
source_id
title
source_url
canonical_url
published_at
summary
section
discovery_method
rank_position
rank_section
fulltext_status
```

Ranking behavior:

- If `rank_position > 0`, the adapter found a source-native rank or ordered surface.
- If `rank_position = 0`, the item is ordered by feed/API/list timestamp or adapter order.
- `discovery_method` explains which pathway was used, such as homepage rank, RSS, API, hot list, or public AJAX.

## Environment Variables

Some social or user-specific sources need local configuration. Examples:

```text
X_HANDLES
TIKTOK_HANDLES
YOUTUBE_CHANNEL_IDS
WECHAT_KEYWORDS
XIAOHONGSHU_KEYWORDS
XIAOYUZHOU_FEEDS
```

If these are not configured, the corresponding adapters may return zero items or show a warning/failure in `source_summary.json` and the HTML report.

Login-state based sources such as Xiaohongshu and Zhihu rely on files under:

```text
config/auth_states/
```

These should remain local to each teammate and should not be committed.

## Team Sharing Model

Recommended sharing method:

1. Put this project, or a future extracted `news-source-console` repo, in the team Git repository.
2. Each teammate clones the repo locally.
3. Each teammate installs dependencies on their own computer.
4. Each teammate runs the CLI with their own local agent and environment.

This avoids sharing cookies, browser sessions, or private local credentials.

## Skill Usage

A Codex/Claude skill can wrap this workflow and lower the usage barrier. The skill should tell the agent:

- When to run `python scripts/news_ingest.py`.
- How to interpret user instructions like "fetch Reuters 20 and BBC 10".
- Where reports are written.
- How to explain failures and missing environment variables.

The skill does not remove the need for local scripts and dependencies. It is an instruction layer over the local tool.
