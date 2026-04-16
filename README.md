# ProductHunt Weekly Tops → Feishu Bitable

[English](#english) | [中文](#中文)

---

<a name="english"></a>
# English

Automatically scrape the **ProductHunt weekly leaderboard** and sync every product into a **Feishu (Lark) Bitable** table — deduplication, team-member enrichment, and IM notifications included.

**917 records synced across 40+ weeks. Zero duplicates.**

---

## Quickstart with Claude Code Skill

The easiest way to use this project is with the included Claude Code skill. Install it once and your Claude agent handles the rest — running syncs, configuring credentials, debugging issues.

### 1. Install the skill

```bash
claude skill install producthunt-feishu-sync.skill
```

### 2. Set up credentials

Your agent will walk you through this, or do it manually:

```bash
cp .env.example .env
# Fill in your credentials (see below)
```

The only required values:

| Variable | Where to find it |
|---|---|
| `FEISHU_APP_ID` | Feishu developer console → your app → Credentials |
| `FEISHU_APP_SECRET` | Same page as above |
| `FEISHU_TABLE_APP_ID` | Open your Bitable → copy the `BASxxx…` token from the URL |
| `FEISHU_TABLE_ID` | The `tblXXX` segment in the same URL |
| `FEISHU_RECEIVER_OPEN_ID` | Feishu developer console → User Info API |
| `PH_COOKIES` | Chrome → F12 → Application → Cookies → producthunt.com → copy all |

> `PH_COOKIES` is strongly recommended — it lets the scraper bypass Cloudflare 403 errors.

### 3. Create Feishu Bitable fields

Add these fields to your table (names are **case-sensitive**):

`PH_Id` · `Product_Name` · `Brief` · `Description` · `Upvote` · `Launch_tags` · `team_members` · `PH_Link` · `Forum` · `Followers` · `Company_Info` · `Week_Range` · `Last_Updated`

### 4. Tell your agent to sync

Once the skill is installed, just describe what you want:

> *"Run the ProductHunt weekly sync"*
> *"Sync last week's PH leaderboard to Feishu"*
> *"The team members are empty, fix it"*
> *"PH没同步，帮我跑一下"*

Your agent reads the skill, runs `wokflow.py`, and handles errors automatically.

---

## Preview

**Core fields** — product name, upvotes, tags, Chinese description, team members, company info, PH link:

![Feishu Bitable - Core Fields](assets/demo1.png)

**Extended fields** — brief, full description, followers, forum link, PH ID, last updated, week range:

![Feishu Bitable - Extended Fields](assets/demo2.png)

---

## How It Works

Data is collected in **two stages**:

**Stage 1 — Weekly leaderboard page (Apollo SSR JSON)**
The PH weekly page embeds a full data snapshot. Scripts read it directly — no API key needed.
→ Fills: `Product_Name`, `Brief`, `Description`, `Upvote`, `Launch_tags`, `team_members`, `PH_Link`, `Forum`, `PH_Id`, `Week_Range`

**Stage 2 — Individual product pages (DrissionPage / real Chromium)**
Three fields aren't in the leaderboard data, so the script opens each product page in a real browser.
→ Fills: `Followers`, `Company_Info`, `team_members` (enriched from `/makers` sub-page)

---

## Manual Usage

If you prefer to run scripts directly without the agent:

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python wokflow.py --once              # run immediately
python wokflow.py                     # daily scheduler (08:00 Asia/Shanghai)
PH_WEEK_OFFSET=-1 python wokflow.py --once   # last week

python scrape_team_drission.py --limit 20    # enrich team members
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Cloudflare 403 | Add fresh `PH_COOKIES` to `.env` (include `cf_clearance`) |
| Field missing in Feishu | Create the field — names are case-sensitive |
| Feishu auth error | Check app ID/secret; enable Bitable + Message permissions |
| `team_members` empty | PH may have updated its page — ask your agent to check the selectors |

When in doubt, just tell your agent what's wrong. The skill contains the full debugging guide.

---

## License

MIT — see [LICENSE](LICENSE).

---

<a name="中文"></a>
# 中文

自动抓取 **ProductHunt 每周榜单**，同步到**飞书多维表格**，支持去重、团队成员补充爬取和 IM 消息通知。

**已同步 40+ 周、917 条记录，零重复。**

---

## 用 Claude Code Skill 快速上手

最简单的用法是安装仓库内附的 Claude Code skill。装好之后，你的 Claude agent 负责跑同步、配置密钥、处理报错，不需要你手动操作。

### 1. 安装 skill

```bash
claude skill install producthunt-feishu-sync.skill
```

### 2. 填写密钥

agent 会引导你完成，或者手动配置：

```bash
cp .env.example .env
# 填入你的密钥（见下表）
```

必填项：

| 变量名 | 在哪里找 |
|---|---|
| `FEISHU_APP_ID` | 飞书开发者后台 → 你的应用 → 凭证与基础信息 |
| `FEISHU_APP_SECRET` | 同上 |
| `FEISHU_TABLE_APP_ID` | 打开多维表格 → URL 里的 `BASxxx…` |
| `FEISHU_TABLE_ID` | 同 URL 里的 `tblXXX` |
| `FEISHU_RECEIVER_OPEN_ID` | 飞书开发者后台 → 用户信息 API |
| `PH_COOKIES` | Chrome → F12 → Application → Cookies → producthunt.com → 全部复制 |

> 强烈推荐填 `PH_COOKIES`，可以绕过 Cloudflare 403 限制。

### 3. 建飞书多维表格字段

在你的数据表中添加以下字段（**大小写完全一致**）：

`PH_Id` · `Product_Name` · `Brief` · `Description` · `Upvote` · `Launch_tags` · `team_members` · `PH_Link` · `Forum` · `Followers` · `Company_Info` · `Week_Range` · `Last_Updated`

### 4. 让 agent 去跑

skill 装好之后，直接说你想做什么：

> *"帮我跑一下 ProductHunt 周榜同步"*
> *"同步上周的 PH 榜单到飞书"*
> *"team members 都是空的，帮我修一下"*
> *"Run the PH weekly sync"*

agent 会读取 skill、运行脚本、自动处理报错。

---

## 效果预览

**核心字段** — 产品名、票数、标签、中文描述、团队成员、公司信息、PH 链接：

![飞书多维表格 - 核心字段](assets/demo1.png)

**扩展字段** — Brief、完整描述、Followers、论坛链接、PH ID、更新时间、周次：

![飞书多维表格 - 扩展字段](assets/demo2.png)

---

## 工作原理

数据分 **两个阶段** 采集：

**阶段一 — 周榜页面 Apollo SSR JSON**
周榜页面内嵌完整数据快照，脚本直接读取，无需 API Key。
→ 填充：`Product_Name`、`Brief`、`Description`、`Upvote`、`Launch_tags`、`team_members`、`PH_Link`、`Forum`、`PH_Id`、`Week_Range`

**阶段二 — 产品独立页面（DrissionPage 真实 Chromium）**
三个字段不在周榜数据中，脚本用真实浏览器逐页抓取。
→ 填充：`Followers`、`Company_Info`、`team_members`（来自 `/makers` 子页面的完整版）

---

## 手动运行

如果想不通过 agent 直接跑脚本：

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python wokflow.py --once               # 立即执行一次
python wokflow.py                      # 每天 08:00 定时任务
PH_WEEK_OFFSET=-1 python wokflow.py --once    # 上周数据

python scrape_team_drission.py --limit 20     # 补爬团队成员
```

---

## 常见问题

| 问题 | 解决方法 |
|---|---|
| Cloudflare 403 | 补充 `PH_COOKIES`（确保包含 `cf_clearance`） |
| 飞书字段找不到 | 建立缺失字段，注意大小写 |
| 飞书 Token 报错 | 检查 App ID/Secret，开通多维表格 + 消息权限 |
| `team_members` 为空 | PH 可能改版了，让 agent 帮你检查选择器 |

遇到问题直接告诉 agent 哪里不对，skill 里包含完整的调试指南。

---

## License

MIT — 详见 [LICENSE](LICENSE)。
