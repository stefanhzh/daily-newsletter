# daily-newsletter

`daily-newsletter` 是一个面向投资者视角的通用新闻日报流水线。它会从多源新闻和技术动态源抓取内容，完成候选池构建、分类、过滤、聚类、评分，并最终输出中文 Markdown / HTML 日报。

## 项目定位

本项目的目标不是做“新闻搬运”，而是做一套可复用、可调权重、可回测的信息筛选系统：

- 从全球新闻、财经媒体、技术源、平台热榜等来源构建候选池。
- 按投资者关心的板块输出重要事件。
- 用规则评分控制来源权重、平台权重、原生排名、多源报道等确定性因素。
- 用可选模型评分补充语义判断，例如重要性、投资相关性、长期影响、噪音/软文判断。
- 最终排序分数始终由代码公式计算，便于回测和人工反馈校准。

## 当前能力

- 过去 24 小时新闻候选池抓取。
- 多 source adapter 接入与标准化。
- 分类、过滤、事件聚类。
- 候选项和事件簇评分。
- 中文标题和摘要输出。
- 按板块渲染 Markdown / HTML 日报。
- 技术动态板块，可单独呈现技术热点。
- 可选模型评分；开发测试时也可以只用 heuristic 跑通全流程。

## 日报板块

默认面向投资者阅读顺序组织内容：

- 地缘政治
- 宏观经济
- 产业趋势
- 资本市场与交易
- 科技进展
- 技术动态
- 政策监管
- 风险事件

## 流水线

1. 从 `config/sources.json` / `config/sources.yaml` 读取 source registry。
2. 通过 `scripts/ingest/` 下的 adapter 抓取和标准化原始内容。
3. 生成候选新闻池。
4. 使用 `scripts/classification/` 完成分类。
5. 使用 `scripts/filters/` 过滤噪音和低相关内容。
6. 使用 `scripts/clustering/` 聚合相关报道为事件簇。
7. 使用 `scripts/scoring/` 计算规则分、模型语义分和最终排序分。
8. 输出 Markdown / HTML 报告到 `reports/`。

## 快速开始

建议使用 Python 3.11 或 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-optional.txt
playwright install chromium
```

使用 heuristic 评分跑一版 24 小时日报：

```powershell
python scripts\score_candidate_pool.py --all-sources --hours 24 --scoring-mode heuristic --with-classification --with-clustering --with-tech-dynamics --render-html
```

从已有 scoring 结果重新渲染分类 Markdown / HTML：

```powershell
python scripts\render_category_md.py --input reports\scoring\<run-id>\scored_candidate_pool.json
python scripts\render_category_html.py --input reports\scoring\<run-id>\scored_candidate_pool_by_category.md
```

## 模型评分

默认开发路径可以不依赖模型 API，直接使用 heuristic scoring 跑通全流程。生产环境如果需要更好的语义判断，可以配置 OpenAI 或 DeepSeek 等兼容接口。

在本地 `.env` 或 shell 环境变量中配置：

```powershell
$env:OPENAI_API_KEY="..."
$env:DEEPSEEK_API_KEY="..."
```

模型评分提示词位于：

```text
config/model_scoring_prompt.md
```

模型只负责输出结构化语义维度，不直接决定最终排序。最终分数由代码公式计算，方便后续做回测、阈值调参和人工反馈校准。

## 配置说明

- `config/sources.json` / `config/sources.yaml`：新闻源注册表。
- `config/source_presets.json`：source 分组和预设。
- `config/category_rules.json`：分类规则。
- `config/clustering_rules.json`：聚类规则。
- `config/scoring.json` / `config/scoring.yaml`：评分权重和默认参数。
- `config/thresholds.json` / `config/thresholds.yaml`：筛选阈值。
- `config/source_native_noise_map.json`：平台原生噪音过滤规则。
- `config/source_native_taxonomy_map.json`：平台原生分类映射。
- `config/model_scoring_prompt.md`：可选模型语义评分提示词。

## 本地密钥和登录态

代码和 config 可以进入公开仓库，但密钥、cookie、浏览器登录态和本地运行产物必须在新环境单独配置，不应提交。

这些路径默认不入仓：

```text
.env
config/auth_states/
reports/
data/
artifacts/
*.storage_state.json
translation_cache.json
```

如果某些 source 需要登录态，请在新机器上重新登录并生成本地 Playwright storage state，不要把个人 cookie 或浏览器状态复制进仓库。

## Codex Skill

本仓库包含可复用的 Codex skill：

```text
skills/daily-newsletter-report/
```

它记录了日报全流程的运行说明、环境配置、发布清单和常用排障方式，适合作为下一步自动化日报生产的操作手册。

## 仓库边界

这个 public repo 只应包含日报主线代码、配置和文档。以下内容不应提交：

- API key、`.env`、token、cookie。
- 浏览器登录态和 storage state。
- 生成的日报报告和缓存。
- 原始付费源导出数据。
- 与日报主线无关的探索项目。

## 当前状态

这是一个可运行的早期版本，重点是先把 ingest、classification、clustering、scoring、rendering 的主线流程沉淀下来。后续建议继续完善：

- 更稳定的模型评分调用与失败降级。
- 评分回测和人工 review feedback。
- 更细的 source tier / source rank 校准。
- 日报 UI 和技术动态板块的持续打磨。
- 新环境部署脚本和定时运行方案。
