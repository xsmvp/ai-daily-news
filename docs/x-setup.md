# X / Twitter 信源配置

X 是海外内容里唯一能拿到「从业者原创观点」的渠道，30 个账号在配置里，靠 cookie 免登录 API 抓取。

## 1. 取 cookie

用**独立小号**登录 `x.com`（主号被风控的成本太高），然后：

- Chrome / Edge：F12 → **Application** → Storage → Cookies → `https://x.com`
- Firefox：F12 → **Storage** → Cookies

只要两个值：

| Cookie | 长度（参考） | 有效期 | 说明 |
|---|---|---|---|
| `auth_token` | 40 字符 | 约 1 年 | 登录凭证，HttpOnly |
| `ct0` | 160 字符 | 数周 | CSRF token，最先失效的就是它 |

写进 `.env`：

```bash
X_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
X_CT0=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PROXY_URL=http://127.0.0.1:7897   # 国内本机需要；GitHub Actions 留空
```

## 2. 先本地验证

```bash
python scripts/collect_x.py --handle karpathy   # 单账号，约 4 秒
python scripts/collect_x.py                     # 前 3 个账号
python scripts/collect_x.py --all               # 全部 30 个，约 3 分钟
```

正常输出：

```
  Fetching X: @swyx
    Got 4 tweets

=== 4 tweets ===
  @swyx                 4 tweets
```

`Got 0 tweets` 不是错误——说明该账号在时间窗内没有新推文。用 `--hours 72` 放宽再看。

## 3. GitHub Actions

仓库 → Settings → Secrets and variables → **Actions** → New repository secret：

| Name | Value |
|---|---|
| `X_AUTH_TOKEN` | auth_token 的值 |
| `X_CT0` | ct0 的值 |

**不要**配 `PROXY_URL`：runner 在美国，直连 x.com；设成空串也无害（代码把空串当未设置）。

不花 token 地验证 cookie 是否可用：Actions → **AI Daily Digest** → Run workflow → mode 选 `x_check`。这个模式只跑 `scripts/collect_x.py --all`，不调 LLM。

## 4. 已知问题与处理

### twikit 与 X 的两处不兼容（已在代码中修补）

`twikit` 最新版就停在 2.3.3（2025-02），之后 X 改了两处，导致原版必然失败：

| 现象 | 原因 | 处理 |
|---|---|---|
| `Couldn't get KEY_BYTE indices` | 分片清单从 `"ondemand.s":"<hash>"` 改成 `id:"ondemand.s"` + `id:"<hash>"` 两张表 | `src/collectors/twikit_patch.py` 重写了哈希解析 |
| `KeyError: 'urls'` | X 去掉了 `legacy.entities.description.urls` | 采集器不再用 twikit 的 `User` / `Tweet` 对象，直接解析 GraphQL JSON |

因此 `requirements.txt` 把 `twikit` 锁在 `2.3.3`。**升级 twikit 前先确认这两处补丁是否仍必要**，否则可能静默失效。

### 其他

| 现象 | 处理 |
|---|---|
| `Rate limited, waiting 60s...` 反复出现 | 单会话请求过密。日常每天跑一次不会触发；调试时用 `--handle` 只测单个账号 |
| 全部账号 `Got 0 tweets` | cookie 已失效（尤其 `ct0`），重新执行第 1 步 |
| `Error: status: 403` | 该 IP 被风控。Actions 的机房 IP 有概率触发，换 locale 或改用住宅代理 |
| 日志完全没有 `Fetching X` | 两个 cookie 有一个为空，主流程直接跳过（不会报错） |

## 5. 补充账号

`config/x_accounts.yaml`：

```yaml
accounts:
  - handle: karpathy
    name: Andrej Karpathy
    bio: AI researcher
    weight: high   # high 权重在评分时 ×3
```

`weight: high` 用于给重点账号加权。当前 30 个账号，24 小时窗口实测约 40~60 条推文，17 个账号有产出。
