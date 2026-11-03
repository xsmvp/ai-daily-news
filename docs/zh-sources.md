# 国内信息源可用性记录

配置见 `config/feeds_zh.yaml`，**默认开启**。要关闭：`ENABLE_ZH_SOURCES=0`。

## 实测结果（2026-10-30）

| 源 | 入口 | 状态 | 说明 |
|---|---|---|---|
| 量子位 | `qbitai.com/feed` | 可用 | AI 垂类，tier 1 |
| Qwen 官方博客 | `qwenlm.github.io/blog/index.xml` | 可用 | Atom，更新慢，24h 内常无新文 |
| 雷锋网 | `leiphone.com/feed` | 可用 | AI 产业内容多，tier 2 |
| 极客公园 | `geekpark.net/rss` | 可用 | tier 2 |
| InfoQ 中文 | `infoq.cn/feed` | 可用 | tier 2 |
| 爱范儿 | `ifanr.com/feed` | 可用 | tier 2 |
| 钛媒体 | `tmtpost.com/rss.xml` | 可用 | tier 2 |
| IT之家 | `ithome.com/rss/` | 可用 | 60 条/次，AI 约占一半，tier 3 |
| 开源中国 | `oschina.net/news/rss` | 可用 | tier 3 |
| 掘金 | `juejin.cn/rss` | 可用 | tier 3 |
| Solidot | `solidot.org/index.rss` | 可用 | tier 3 |
| cnBeta | `cnbeta.com.tw/backend.php` | 可用但默认关闭 | 150 条/次，噪音最大 |
| 36氪 | RSSHub `/36kr/newsflashes` | 可用 | 官方 `/feed` 已废；快讯混大量股市行情 |
| 虎嗅 | RSSHub `/huxiu/article` | 可用 | 官方 RSS 被 WAF 拦截（超时） |
| 机器之心 | 无 | 不可用 | 官网 `/rss` 返回 HTML；RSSHub 路由 503 |
| 新智元 / 机器之心公众号 | 无 | 不可用 | 仅微信公众号，需 wechat2rss 类自建服务 |
| 界面新闻 | `a.jiemian.com/...rss` | 不可用 | 502 |
| 智东西 | `zhidx.com/feed` | 不可用 | 500 |
| 品玩 / CSDN AI | — | 不可用 | 返回 HTML 非 feed |
| 阿里云 / 腾讯云开发者社区 | `/rss` | 不可用 | 404 |
| 澎湃科技 | `feedx.net/rss/thepaper.xml` | 不可用 | 数据停在 2025-12，镜像失效 |
| 晚点 LatePost | `latepost.com/rss` | 不可用 | 404 |

厂商官方站（DeepSeek / 智谱 / 月之暗面 / 阿里云百炼 / 百度 AI / 火山引擎 / MiniMax / 阶跃星辰 / 商汤）均无 RSS，只有 HTML 页面，需单独的网页抓取器。当前未实现。

## RSSHub 镜像

36氪和虎嗅依赖 `https://rsshub.rssforever.com` 公有镜像。该镜像不稳定（实测 36氪资讯路由超时、机器之心路由 503）。失效时按以下顺序替换 `rss:` 字段：

1. 自建实例（推荐）：`docker run -d -p 1200:1200 diygod/rsshub`，然后改为 `http://<host>:1200/...`
2. 其他公有镜像：`hub.slarker.me`（实测可用）

## 维护要点

- 验证单个源是否还活着：`python scripts/collect_zh.py`（只看采集结果，不调用 LLM、不发布），加 `--source 量子位` 只看某个源。
- 单个源失效时把 `enabled` 设为 `false`，不要删配置，方便日后恢复。
- 泛科技源（tier 3）必须保持 `filter_mode: strict`，否则一天几百条无关内容会冲掉日报。
- `filter_scope: title` 是刻意的：按摘要判定会让融资、生物医药类稿件因为顺带提了一句 AI 而混进来。
- 新增源后先跑一次 `collect_rss(24, config_path='config/feeds_zh.yaml')` 看 `skipped off-topic` 比例，判断关键词表和 tier 是否合适。
