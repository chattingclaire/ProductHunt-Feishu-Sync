# ProductHunt Weekly Tops → Feishu Bitable

[English](#english) | [中文](#中文)

---

<a name="english"></a>
# English

Automatically scrape the **ProductHunt weekly leaderboard** and sync every product into a **Feishu (Lark) Bitable** table — deduplication, team-member enrichment, and IM notifications included.

**917 records synced across 40+ weeks. Zero duplicates.**

## Claude Code Skill

A ready-to-use Claude Code skill ships with this repo. Install it once and your agent can run syncs, configure credentials, and debug scraping issues on its own.

```bash
claude skill install producthunt-feishu-sync.skill
```

Triggers automatically on: `"run the PH weekly sync"` · `"PH没同步"` · `"飞书没更新"` · `"team members抓不到"` · `"Cloudflare 403"`

---

## Preview

**Core fields** — product name, upvotes, tags, Chinese description, team members, company info, PH link:

![Feishu Bitable - Core Fields](assets/demo1.png)

**Extended fields** — brief, full description, followers, forum link, PH ID, last updated, week range:

![Feishu Bitable - Extended Fields](assets/demo2.png)

---

## How It Works

Data is collected in **two stages**:

### Stage 1 — ProductHunt Weekly Page (Apollo SSR JSON)

The weekly leaderboard page embeds a full Apollo data snapshot. The script reads this JSON directly — **no API key required**.

| Feishu Field | Source | Notes |
|---|---|---|
| `Product_Name` | `name` | Product name |
| `Brief` | `tagline` | One-line tagline |
| `Description` | `description` | Full product description |
| `Upvote` | `votesCount` | Weekly upvote count |
| `Launch_tags` | `topics` | Category tags (AI, Productivity, …) |
| `team_members` | `makers[]` | Maker names from leaderboard |
| `PH_Link` | `url` | Product Hunt URL |
| `Forum` | derived | PH discussion thread link |
| `PH_Id` | `id` | Unique ID — deduplication key |
| `Week_Range` | computed | ISO week, e.g. `2025-W44` |
| `Last_Updated` | computed | Sync timestamp |

### Stage 2 — Individual Product Pages (DrissionPage)

Three fields are not in the leaderboard data. The script opens each product page in a real Chromium browser to scrape them:

| Feishu Field | Scraped From |
|---|---|
| `Followers` | Product main page — follower count |
| `Company_Info` | Product main page → "Company Info" sidebar |
| `team_members` *(enriched)* | `/makers` sub-page — full team list |

> `scrape_team_drission.py` can re-run Stage 2 independently on existing records at any time.

---

## Architecture

```
producthunt.com/leaderboard/weekly/…
        │
        ▼  DrissionPage (Chromium, bypasses Cloudflare)
   Apollo SSR JSON
        │
        ▼  parse
   Product_Name · Brief · Description · Upvote
   Launch_tags · team_members · PH_Link · PH_Id …
        │
        ▼  per-product pages (Stage 2)
   Followers · Company_Info · team_members (enriched)
        │
        ├──▶  Feishu Bitable  (upsert by PH_Id)
        └──▶  Feishu IM notification
```

---

## Setup

**Prerequisites:** Python 3.9+, Chrome installed locally, Feishu developer app (Bitable + Message permissions)

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in your credentials (see table below)
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `FEISHU_APP_ID` | Yes | Feishu / Lark app ID |
| `FEISHU_APP_SECRET` | Yes | Feishu / Lark app secret |
| `FEISHU_TABLE_APP_ID` | Yes | Bitable app token (`BAS…`) |
| `FEISHU_TABLE_ID` | Yes | Table ID inside the Bitable |
| `FEISHU_RECEIVER_OPEN_ID` | Yes | IM notification recipient Open ID |
| `PH_COOKIES` | Recommended | Cookie string — prevents Cloudflare 403 |
| `PH_WEEK_OFFSET` | No | `-1` = last week, `0` = this week |
| `PH_WEEKLY_URL` | No | Override weekly URL directly |
| `TIMEZONE` | No | Default `Asia/Shanghai` |
| `ENABLE_TEAM_SCRAPER` | No | `true` = auto-run team enrichment after sync |
| `http_proxy` / `https_proxy` | No | e.g. `http://127.0.0.1:7890` |

### Getting ProductHunt Cookies

Chrome → F12 → Application → Cookies → `https://www.producthunt.com` → copy all as `key1=value1; key2=value2` → paste as `PH_COOKIES=…`

Key cookies: `_producthunt_session`, `cf_clearance`, `__cf_bm`

### Feishu Bitable Fields

Create these fields (names are **case-sensitive**):

`PH_Id` · `Product_Name` · `Brief` · `Description` · `Upvote` · `Launch_tags` · `team_members` · `PH_Link` · `Forum` · `Followers` · `Company_Info` · `Week_Range` · `Last_Updated`

---

## Usage

```bash
# Run once immediately
python wokflow.py --once

# Daily scheduler (08:00 Asia/Shanghai)
python wokflow.py

# Last week / specific week
PH_WEEK_OFFSET=-1 python wokflow.py --once
PH_WEEKLY_URL=https://www.producthunt.com/leaderboard/weekly/2025/10 python wokflow.py --once

# Enrich team members for existing records
python scrape_team_drission.py --dry-run     # preview only
python scrape_team_drission.py --limit 20    # up to 20 records
python scrape_team_drission.py               # all records
```

---

## Page Structure & Maintenance

PH occasionally updates its frontend. If Stage 2 fields stop populating, verify the selectors below still match the current page using Chrome DevTools.

| Field | Selector | Verify On |
|---|---|---|
| `Followers` | `css:p.text-14.font-medium.text-gray-700` (contains "X followers") | Any product page |
| `Company_Info` | `text:Company Info` → `css:a[class*="stroke-gray-900"][target="_blank"]` | Product page with a website |
| `team_members` | `css:a[href$="/makers"]` → `css:a[href^="/@"].font-semibold` | `/products/<slug>/makers` |

If a selector breaks: update it in `wokflow.py` (Stage 2 function) **and** `scrape_team_drission.py`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Cloudflare 403 | Add fresh `PH_COOKIES` (especially `cf_clearance`) |
| Field missing in Feishu | Create the field — names are case-sensitive |
| Feishu auth error | Verify app ID/secret; enable Bitable + Message permissions |
| Records not deduplicating | Confirm `PH_Id` field exists |
| DrissionPage can't find Chrome | Install Chrome locally |
| `team_members` empty | Check DrissionPage selectors (PH may have updated page) |

---

## Project Structure

```
wokflow.py                 # Main workflow: Stage 1 + Stage 2 + Feishu sync
scrape_team_drission.py    # Standalone Stage 2 team enrichment
scrape_empty_records.py    # Re-process records missing data
update_from_weekly.py      # Back-fill historical weeks
requirements.txt
.env.example               # Credential template
producthunt-feishu-sync.skill  # Claude Code skill (install with claude skill install)
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

PRs and issues welcome. If PH updates its page structure and scraping breaks, open an issue with the relevant HTML snippet.

---

<a name="中文"></a>
# 中文

自动抓取 **ProductHunt 每周榜单**，将每个产品同步到**飞书多维表格**，支持去重、团队成员补充爬取和 IM 消息通知。

**已同步 40+ 周、917 条记录，零重复。**

## Claude Code Skill

仓库内含开箱即用的 Claude Code skill。装上之后，agent 可以自主完成同步、配置和调试，不需要你手动操作。

```bash
claude skill install producthunt-feishu-sync.skill
```

自动触发词：`"重新跑一下周榜"` · `"PH没同步"` · `"飞书没更新"` · `"team members抓不到"` · `"403报错"`

---

## 效果预览

**核心字段** — 产品名、票数、标签、中文描述、团队成员、公司信息、PH 链接：

![飞书多维表格 - 核心字段](assets/demo1.png)

**扩展字段** — Brief、完整描述、Followers、论坛链接、PH ID、更新时间、周次：

![飞书多维表格 - 扩展字段](assets/demo2.png)

---

## 数据采集方式

数据分 **两个阶段** 采集：

### 阶段一：PH 周榜页面的 Apollo SSR JSON

周榜页面内嵌了完整的 Apollo 数据快照，脚本直接读取，**无需任何 API Key**。

| 飞书字段 | 原始字段 | 说明 |
|---|---|---|
| `Product_Name` | `name` | 产品名称 |
| `Brief` | `tagline` | 一句话 tagline |
| `Description` | `description` | 完整描述 |
| `Upvote` | `votesCount` | 本周票数 |
| `Launch_tags` | `topics` | 分类标签 |
| `team_members` | `makers[]` | 榜单中的 Maker 名称 |
| `PH_Link` | `url` | ProductHunt 产品链接 |
| `Forum` | 计算 | PH 讨论帖链接 |
| `PH_Id` | `id` | 唯一 ID，去重用 |
| `Week_Range` | 计算 | ISO 周次，如 `2025-W44` |
| `Last_Updated` | 计算 | 同步时间戳 |

### 阶段二：产品独立页面（DrissionPage 爬取）

以下字段在周榜数据中不存在，需用 DrissionPage 打开真实 Chromium 浏览器逐页抓取：

| 飞书字段 | 抓取位置 |
|---|---|
| `Followers` | 产品主页 — 关注者数量 |
| `Company_Info` | 产品主页 → Company Info 侧边栏 |
| `team_members`（补充） | 产品 `/makers` 子页面 — 完整团队列表 |

> `scrape_team_drission.py` 可随时单独运行，为已有记录补充团队成员信息。

---

## 安装使用

**前置条件：** Python 3.9+、本地已安装 Chrome、飞书开发者应用（需开通多维表格 & 消息权限）

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 填入你的密钥
```

### 环境变量

| 变量名 | 是否必填 | 说明 |
|---|---|---|
| `FEISHU_APP_ID` | 是 | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 是 | 飞书应用 App Secret |
| `FEISHU_TABLE_APP_ID` | 是 | 多维表格 App Token（`BAS…` 开头） |
| `FEISHU_TABLE_ID` | 是 | 数据表 ID |
| `FEISHU_RECEIVER_OPEN_ID` | 是 | IM 通知接收人 Open ID |
| `PH_COOKIES` | 强烈推荐 | Cookie 字符串，防 Cloudflare 403 |
| `PH_WEEK_OFFSET` | 否 | `-1` = 上周，`0` = 本周 |
| `PH_WEEKLY_URL` | 否 | 直接指定周榜 URL |
| `TIMEZONE` | 否 | 默认 `Asia/Shanghai` |
| `ENABLE_TEAM_SCRAPER` | 否 | `true` = 主同步后自动补爬团队成员 |
| `http_proxy` / `https_proxy` | 否 | 如 `http://127.0.0.1:7890` |

### 获取 PH Cookies

Chrome → F12 → Application → Cookies → `https://www.producthunt.com` → 复制全部，格式 `key1=value1; key2=value2` → 填入 `PH_COOKIES=…`

重点：`_producthunt_session`、`cf_clearance`、`__cf_bm`

### 飞书多维表格字段

以下字段名**大小写敏感**，需完全一致：

`PH_Id` · `Product_Name` · `Brief` · `Description` · `Upvote` · `Launch_tags` · `team_members` · `PH_Link` · `Forum` · `Followers` · `Company_Info` · `Week_Range` · `Last_Updated`

---

## 常用命令

```bash
# 立即执行一次
python wokflow.py --once

# 启动定时任务（每天 08:00）
python wokflow.py

# 上周 / 指定周
PH_WEEK_OFFSET=-1 python wokflow.py --once
PH_WEEKLY_URL=https://www.producthunt.com/leaderboard/weekly/2025/10 python wokflow.py --once

# 补爬团队成员
python scrape_team_drission.py --dry-run     # 仅预览
python scrape_team_drission.py --limit 20    # 最多 20 条
python scrape_team_drission.py               # 全部
```

---

## 页面结构维护

PH 会不定期更新前端。如果阶段二字段抓不到，用 Chrome DevTools 对照以下选择器检查当前页面：

| 字段 | 选择器 | 检查页面 |
|---|---|---|
| `Followers` | `css:p.text-14.font-medium.text-gray-700`（含 "X followers"） | 任意产品页 |
| `Company_Info` | `text:Company Info` → `css:a[class*="stroke-gray-900"][target="_blank"]` | 有官网的产品页 |
| `team_members` | `css:a[href$="/makers"]` → `css:a[href^="/@"].font-semibold` | `/products/<slug>/makers` |

选择器失效时，同步更新 `wokflow.py`（阶段二函数）和 `scrape_team_drission.py`。

---

## 常见问题

| 问题 | 解决方法 |
|---|---|
| Cloudflare 403 | 补充 `PH_COOKIES`（确保包含 `cf_clearance`） |
| 飞书字段找不到 | 建立缺失字段，注意大小写 |
| 飞书 Token 报错 | 检查 App ID/Secret，开通多维表格 + 消息权限 |
| 记录重复 | 确认 `PH_Id` 字段存在 |
| DrissionPage 找不到 Chrome | 本地安装 Chrome |
| `team_members` 为空 | 检查 DrissionPage 选择器 |

---

## License

MIT — 详见 [LICENSE](LICENSE)。

---

## 贡献

欢迎 PR 和 Issue。PH 改版导致解析失败时，请附上相关 HTML 片段开 Issue。
