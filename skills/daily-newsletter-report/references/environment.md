# Environment And Connector Setup

## What Is Required For The Daily Report

The standard daily-newsletter run is mostly public-source based. A new environment can run the core daily report with:

- Python 3.11+ or 3.12.
- Packages from `requirements.txt`.
- Optional packages from `requirements-optional.txt` for browser/fulltext features.
- Network access to public news, RSS, GitHub, Google Trends, Bilibili, Zhihu, and similar pages.
- No mandatory account login for the default source-ingest/scoring/render loop.

Minimum setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-optional.txt
playwright install chromium
```

If PowerShell blocks activation, use the venv Python directly:

```powershell
.\.venv\Scripts\python.exe scripts\news_ingest.py --preset default --lookback-hours 24
```

## Source Adapter Registry

Source adapters are registered in:

```text
scripts/ingest/registry.py
```

The default source set is configured in:

```text
config/source_presets.json
```

Source tier, role, group, and preference metadata are configured in:

```text
config/sources.json
config/sources.yaml
```

Noise and category behavior:

```text
config/source_native_noise_map.json
config/source_native_taxonomy_map.json
config/source_category_overrides.json
config/category_rules.json
config/clustering_rules.json
```

Scoring and thresholds:

```text
config/scoring.json
config/scoring.yaml
config/thresholds.json
config/thresholds.yaml
```

## Adapter Classes In The Default Preset

The default preset currently references adapters such as:

- Global news: `reuters`, `ap`, `bbc`, `cnbc`, `bloomberg`, `ft`, `wall-street-journal`, `nikkei-asia`, `politico`, `axios`, `semafor`, `zerohedge`, `scmp`.
- China/market news: `caixin`, `yicai`, `cailian`, `wallstreetcn`, `wind-news`, `ths-hotrank`, `36kr`, `gelonghui`, `tradingview-news`, `unusual-whales`.
- AI/tech sources: `openai-blog`, `anthropic-news`, `a16z-blog`, `y-combinator`, `huggingface`, `semianalysis`, `stratechery`, `latent-space`, `lennys-newsletter`, `lesswrong`, `lobsters`, `techcrunch`.
- Technical dynamics and social discovery: `github-trending`, `github-issues-trends`, `google-trends`, `bilibili-popular`, `zhihu-hot`, `reddit-hot`, `youtube-channel-feeds`, `tiktok-profile-signals`.
- Low-frequency/optional social and communication sources: `xiaohongshu-search`, `x-account-posts`, `wechat-search`, `xiaoyuzhou-feeds`, `discord-blog`, `telegram-blog`.

Some adapters intentionally return zero items when no public content is available or when no account/session is configured.

## Optional Auth State

The daily-newsletter ingest layer supports optional Playwright storage-state files for sources that benefit from logged-in browsing.

Helpers:

```text
scripts/ingest/auth_state.py
scripts/ingest/capture_auth_state.py
```

Default auth-state directory:

```text
config/auth_states/
```

Supported capture targets:

```powershell
python scripts\ingest\capture_auth_state.py --source zhihu-hot
python scripts\ingest\capture_auth_state.py --source xiaohongshu-search
```

Useful environment variables:

```powershell
$env:DAILY_NEWSLETTER_AUTH_STATE_DIR="C:\path\to\auth_states"
$env:ZHIHU_HOT_STORAGE_STATE="C:\path\to\zhihu-hot.storage_state.json"
$env:XIAOHONGSHU_SEARCH_STORAGE_STATE="C:\path\to\xiaohongshu-search.storage_state.json"
```

Do not commit `config/auth_states/*.storage_state.json`, browser profiles, cookies, tokens, or session files.

## LLM And Translation

Routine local runs should use:

```powershell
--model-mode heuristic
```

LLM scoring is optional. DeepSeek is supported through an OpenAI-compatible client:

```powershell
$env:DEEPSEEK_API_KEY="..."
python scripts\score_candidate_pool.py --input reports\source_ingest\...\raw_items.json --model-mode llm --model deepseek-chat --limit-model-calls 30
```

OpenAI-compatible fallback:

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_MODEL="gpt-4.1-mini"
```

Translation uses `scripts/localization.py` and a local cache:

```text
reports/scoring/translation_cache.json
```

If `deep_translator` is unavailable or blocked, renderers can still run with missing translations or with `--no-translate`. Prefer fixing the translation environment for production daily output.

## Cross-Platform Search And KOL Watchlist Extras

These are adjacent capabilities, not required for the default daily-newsletter run. If migrating the whole workspace, document and configure them separately.

Observed optional environment variables include:

```text
GITHUB_TOKEN or GH_TOKEN
SCRAPECREATORS_API_KEY
BAIDU_API_KEY
BAIDU_SECRET_KEY
BSKY_HANDLE
BSKY_APP_PASSWORD
WE_MP_RSS_DB_PATHS or WE_MP_RSS_DB_PATH
XIAOHONGSHU_MCP_API_BASE
XIAOHONGSHU_MCP_TOKEN
CHROME_CDP_VERSION_URL
MEDIACRAWLER_HOME
MEDIACRAWLER_XHS_COOKIES
MEDIACRAWLER_UV_BIN
MEDIACRAWLER_LOGIN_TYPE
MEDIACRAWLER_HEADLESS
WEIBO_ACCESS_TOKEN
ZHIHU_COOKIE
TIKHUB_API_KEY
AGENT_BROWSER_BIN
```

These power low-frequency connectors such as WeChat archive search, Xiaohongshu modes, Reddit paid bridge, Baidu search, GitHub API search, Bluesky, and browser-backed WeChat search. They should not be required for the standard HTML/Markdown daily report.

## New Machine Smoke Test

After setup, run:

```powershell
python scripts\news_ingest.py --sources reuters:5 ap:5 bbc:5 caixin:5 github-trending:5 --lookback-hours 24 --source-timeout 45 --jobs 3 --output-dir reports\source_ingest\smoke-new-env
python scripts\score_candidate_pool.py --input reports\source_ingest\smoke-new-env\raw_items.json --model-mode heuristic
```

Then render with the printed `RUN_ID`:

```powershell
python scripts\render_category_md.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 5
python scripts\render_category_html.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 5
```

Expected result:

- Some public sources return items.
- Low-frequency sources may return zero.
- Reports are generated under `reports/source_ingest/` and `reports/scoring/`.
- No API key is needed when using heuristic scoring.

## Publishing To A New GitHub Repo

This repository currently has no remote configured in this workspace. GitHub CLI is usable if `gh auth status` shows an authenticated account.

Recommended safe sequence:

```powershell
gh repo create stefanhzh/daily-newsletter --private --description "Investor-oriented daily news newsletter pipeline" --source . --remote origin
```

Before pushing, audit `.gitignore` and staged files:

```powershell
git status --short
git check-ignore -v skills\daily-newsletter-report\SKILL.md
git ls-files
```

Important: the current `.gitignore` may ignore many `daily-newsletter` files because it was previously focused on cross-platform research. A real project release should explicitly include the active daily-newsletter code and configs, while continuing to exclude:

- `reports/`
- `artifacts/`
- `data/`
- `experiments/`
- `.env*`
- tokens, cookies, sessions
- `config/auth_states/`
- browser profiles
- model caches

Do not push until the user chooses public/private visibility and confirms whether generated reports should be excluded.
