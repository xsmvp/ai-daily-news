# AI Daily News

> 自部署的 AI 资讯流水线：从 RSS 和 X 拉取信源，跨源去重打分，让 LLM 整理成日报，可选生成播客音频，发布到任何你想要的地方。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) | **简体中文**

<p align="center">
  <img src="docs/screenshot-headlines.png" width="240" alt="今日要闻" />
  <img src="docs/screenshot-opinions.png" width="240" alt="值得关注的观点" />
  <img src="docs/screenshot-products.png" width="240" alt="产品动态" />
</p>
<p align="center"><em>发布到微信公众号的实际效果。默认中文，<code>DIGEST_LANG=en</code> 切换英文。</em></p>

## 为什么再造一个 AI 资讯工具？

市面上 AI 新闻聚合不少，但这个项目认真做了几件事：

- **配一次，每天自动出报**：自带 GitHub Actions 定时任务，配好一次之后每天自动跑、自动发布到你指定的渠道。零服务器、走 Actions 免费额度。
- **多源去重 + 打分**：三层去重（URL → 标题相似度 → 摘要相似度）+ 时间衰减打分，5 家外媒报同一件事会合并成一条交叉验证的条目，而不是塞进 5 行重复信息。
- **开箱即用的播客音频**：每篇日报都能用 Podcastfy + Edge TTS 自动生成中文双人播客 MP3，公众号内嵌、Telegram 推送都行。
- **可插拔发布器**：本地 Markdown、微信公众号、Telegram 频道，按 env 自动启用，加个新平台只要 30 行。
- **认真服务中文场景**：默认中文 prompt 调教过、自带敏感词过滤（默认关闭）、支持微信公众号发布、Moonshot/Kimi 这类国内 LLM 直接用。

样例日报在 [`examples/sample-digest.md`](examples/sample-digest.md)。

## 快速开始

```bash
git clone https://github.com/<you>/ai-daily-news && cd ai-daily-news
pip install -r requirements.txt
cp .env.example .env  # 至少填上 LLM_API_KEY
python src/handler.py 24    # 24 = 回看多少小时
```

日报会写到 `data/digest-YYYY-MM-DD.md`。如果不配置任何 publisher，这就是唯一输出 —— 适合接到你自己的工作流里。

### Docker

```bash
cp .env.example .env  # 改一下
docker compose up
```

## 每天自动跑

仓库自带 [`.github/workflows/daily.yml`](.github/workflows/daily.yml) —— 一个每天 UTC 00:00 自动执行的 GitHub Actions 工作流。开启方式：

1. Fork 本仓库（这样 Actions 跑在你自己的账号下）
2. Settings → Secrets and variables → Actions → 加上 `LLM_API_KEY` 和你想用的发布渠道凭证（`WECHAT_APP_ID`、`TELEGRAM_BOT_TOKEN` 等）
3. 完事。明早就会有一篇日报落到你配的渠道里。

想换时间？改 `daily.yml` 里的 cron。比如 `'0 22 * * *'` 是 UTC 22:00（北京时间次日早 6:00）。本地 cron / Cloud Run / Lambda 也行，按自己的调度调用 `python src/handler.py 24` 即可。

## 配置信源

- `config/feeds.yaml` — RSS 源，加任意 feed URL 即可。
- `config/feeds_zh.yaml` — 国内 AI/科技信源，默认开启，`ENABLE_ZH_SOURCES=0` 关闭。支持 `tier` 分级权重、`filter_mode: strict` 关键词过滤、`enabled` 单独开关。各源实测可用性见 `docs/zh-sources.md`。
- `config/x_accounts.yaml` — X/Twitter 账号，`weight: high|medium`，high 权重账号得分 ×3。
- `config/sensitive_words.yaml` — 可选的内容过滤（默认关闭，`ENABLE_CONTENT_FILTER=1` 打开；适合发到国内平台）。

X 抓取需要 `X_AUTH_TOKEN` 和 `X_CT0` 两个 cookies（浏览器开发者工具里复制）。不配的话流水线只跑 RSS。取 cookie、GitHub Actions 里怎么配、以及 twikit 与 X 的两处不兼容如何修补，见 `docs/x-setup.md`。

单独验证某一路信源（不花 LLM token）：

```bash
python scripts/collect_zh.py --source 量子位   # 国内源
python scripts/collect_x.py --handle karpathy  # 单个 X 账号
```

## 配置发布渠道

每个配好 env 的 publisher 会自动启用。想限定只跑某几个：`PUBLISHERS=markdown,telegram`。

| 发布器 | 环境变量 | 输出 |
|---|---|---|
| `markdown` | （永远启用） | `data/digest-YYYY-MM-DD.md` |
| `telegram` | `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` | 发到频道，有音频就一起推 |
| `wechat` | `WECHAT_APP_ID`、`WECHAT_APP_SECRET` | 创建公众号草稿，到后台手动发布 |

### 加你自己的发布器

在 `src/publisher/` 下新建一个模块，暴露 `NAME`、`is_configured()`、`publish(digest_md, date_str, **kwargs)` 三个接口，到 `src/publisher/__init__.py` 注册即可。最简模板看 `markdown_file.py`（约 12 行）。

## 流水线

```
采集（RSS + X）  →  打分  →  去重（URL / 标题 / 摘要）  →  分类  →  排序
                                                                            ↓
        ←  发布（markdown / wechat / telegram / …）  ←  音频（可选）  ←  LLM 整理
```

实现细节：
- `src/processor/preprocessor.py` — 打分公式 `log2(互动数) × 账号权重 × 时间衰减(半衰期 24h)`。
- `src/processor/generator.py` — LLM prompt 在 `prompts/digest_zh.md` / `prompts/digest_en.md`，用 `DIGEST_LANG` 切换。
- `src/audio/podcast.py` — 基于 Edge TTS 的中文双人播客，`DISABLE_AUDIO=1` 关闭。

## License

MIT — 详见 [LICENSE](LICENSE)。
