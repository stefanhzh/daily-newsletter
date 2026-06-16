# Daily Newsletter Full Workflow

## Scope

This workflow operates the active `daily-newsletter` project and produces a Chinese investor-oriented daily news report as the final artifact. It assumes the current active code lives under:

```text
scripts/
config/
reports/
```

Ignore old exploration directories unless the user explicitly asks to inspect them.

## Pipeline Map

The production-like local flow is:

```text
source adapters
  -> reports/source_ingest/.../raw_items.json
  -> load_items_from_path()
  -> normalization
  -> relevance and source-native noise filters
  -> classification
  -> prefilter
  -> event clustering
  -> rule scoring + model/heuristic scoring
  -> category renderer
  -> Markdown + HTML daily report
```

Primary entry points:

- `scripts/news_ingest.py`: fetches configured sources and writes raw source previews.
- `scripts/score_candidate_pool.py`: loads raw items, runs classification/filtering/clustering/scoring, writes scored cluster JSON and Markdown.
- `scripts/render_category_md.py`: renders category-grouped Markdown with Chinese titles/summaries and technical dynamics.
- `scripts/render_category_html.py`: renders category-grouped HTML with links, related reports, technical dynamics, and hidden stats.
- `scripts/tech_dynamics.py`: builds the standalone technical-dynamics section from raw source items.
- `scripts/localization.py`: builds and reuses Chinese translation cache.

## Recommended Daily Run

Use a date-stamped ingest directory:

```powershell
python scripts\news_ingest.py --preset default --lookback-hours 24 --source-timeout 45 --jobs 4 --output-dir reports\source_ingest\all-sources-24h-YYYYMMDD
```

Then score the raw pool:

```powershell
python scripts\score_candidate_pool.py --input reports\source_ingest\all-sources-24h-YYYYMMDD\raw_items.json --model-mode heuristic
```

The scoring command prints paths similar to:

```text
json=...\reports\scoring\YYYYMMDD-HHMMSS-ffffff\scored_candidate_pool.json
markdown=...\reports\scoring\YYYYMMDD-HHMMSS-ffffff\scored_candidate_pool.md
```

Render final category reports:

```powershell
python scripts\render_category_md.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 15
python scripts\render_category_html.py --input reports\scoring\RUN_ID\scored_candidate_pool.json --per-category 15
Copy-Item reports\scoring\RUN_ID\scored_candidate_pool_by_category.md reports\scoring\RUN_ID\daily_newsletter_24h_YYYYMMDD.md -Force
Copy-Item reports\scoring\RUN_ID\scored_candidate_pool_by_category.html reports\scoring\RUN_ID\daily_newsletter_24h_YYYYMMDD.html -Force
```

If rendering times out because translation cache is being filled, rerun with a longer timeout. If urgent, use `--no-translate` only as a temporary fallback and tell the user Chinese translations are incomplete.

## Source Behavior

Read source status from:

```text
reports/source_ingest/.../source_summary.json
```

Important details:

- `caixin` has a bounded adapter to avoid source-level timeout; it may return fewer than the requested limit.
- `tiktok-profile-signals` is a weak diagnostic source and should not enter the main news pool.
- `github-trending` and `github-issues-trends` should be rendered in `技术动态`, not in ordinary news categories.
- Some low-frequency sources returning 0 items is normal.
- Major source timeouts should be mentioned in the final answer.

## Category Order

Reports should render in this order:

```text
地缘政治
宏观经济
产业趋势
资本市场与交易
科技进展
技术动态
政策监管
风险事件
```

Do not fill weak categories just for balance. Per-category output defaults to top 15.

## Scoring Policy

Current ranking score is:

```text
final ranking score = rule_score + model_score
```

Rule score is 50 points:

- Platform/source quality: 25 points
- Native rank/homepage rank/list position: 25 points

Model score is 50 points:

- In heuristic mode, local rules estimate semantic usefulness.
- In LLM mode, the model returns structured semantic judgment; code converts it into points.

The model must not directly decide final ranking. Code formula owns the final score.

## LLM Mode

Prefer heuristic mode for local development and routine smoke tests. Use LLM mode only when explicitly requested.

DeepSeek can be used via OpenAI-compatible API:

```powershell
$env:DEEPSEEK_API_KEY="..."
python scripts\score_candidate_pool.py --input reports\source_ingest\...\raw_items.json --model-mode llm --model deepseek-chat --limit-model-calls 30
```

Never persist API keys in the repo. If a key was pasted into chat, recommend rotating it.

## Technical Dynamics

Technical dynamics is a separate section and may include:

- GitHub Trending
- GitHub Issues Trends
- OpenAI / Anthropic / Hugging Face / Latent Space
- TechCrunch / SemiAnalysis / Stratechery / A16Z / YC / LessWrong / Lobsters
- Google Trends / Bilibili / Zhihu / YouTube channel feeds

It should have clickable source links in HTML. GitHub should stay here instead of competing with ordinary news clusters.

## Validation Snippet

Use this quick check after rendering:

```powershell
@'
from pathlib import Path
import json, re
base = Path("reports/scoring/RUN_ID")
html = (base / "daily_newsletter_24h_YYYYMMDD.html").read_text(encoding="utf-8")
md = (base / "daily_newsletter_24h_YYYYMMDD.md").read_text(encoding="utf-8")
payload = json.loads((base / "scored_candidate_pool.json").read_text(encoding="utf-8"))
clusters = payload["clusters"]
print("html_exists", (base / "daily_newsletter_24h_YYYYMMDD.html").exists())
print("md_exists", (base / "daily_newsletter_24h_YYYYMMDD.md").exists())
print("html_read_link_count", html.count('class="read-link"'))
print("html_has_tech", 'id="tech-dynamics"' in html)
print("main_has_tiktok", any(c["source_id"] == "tiktok-profile-signals" for c in clusters))
print("main_has_github", any(c["source_id"] in {"github-trending", "github-issues-trends"} for c in clusters))
print("html_has_ap_photo_caption", "(AP Photo/" in html)
print("html_has_github_tech", "GitHub Trending" in html or "GitHub Issues Trends" in html)
print("nav", re.findall(r'<a href="#[^"]+">([^<]+) <span>', html)[:10])
print("md_sections", re.findall(r"^## (.+)$", md, flags=re.M)[:10])
print("summary", payload["summary"]["raw_item_count"], payload["summary"]["filtered_item_count"], payload["summary"]["cluster_count"], payload["summary"]["score_distribution"])
'@ | python -
```

Also run a syntax smoke check when code changed:

```powershell
python -m py_compile scripts\news_ingest.py scripts\score_candidate_pool.py scripts\render_category_md.py scripts\render_category_html.py
```

## Final Response Template

Use this shape:

```text
已生成过去 24 小时新闻日报：

- [HTML 日报](ABSOLUTE_PATH)
- [Markdown 日报](ABSOLUTE_PATH)

本轮结果：抓取 X 条原始候选，过滤后 Y 条，聚合为 Z 个事件簇；分数区间 A-B，均值 C。HTML 已验证分类顺序正确，主新闻里没有 TikTok/GitHub 噪音，GitHub 仍保留在“技术动态”，AP Photo 图注也未进入日报。

源缺口：...。评分使用 heuristic/LLM。
```

Keep it concise unless the user asks for the full run log.

## Git Notes

This repository may ignore `scripts/*`, `config/*`, and `reports/`. If the user asks to commit skill files, check `.gitignore` and use a deliberate add strategy. Do not stage unrelated dirty work.
