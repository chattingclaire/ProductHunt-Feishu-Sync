---
name: producthunt-feishu-sync
description: >
  Complete guide for the ProductHunt Weekly → Feishu Bitable sync project.
  Use this skill whenever the user wants to: run the PH weekly sync, scrape
  ProductHunt leaderboard data, sync PH data to Feishu (Lark) Bitable,
  enrich records with Followers / Company Info / team members, debug
  DrissionPage selectors when PH updates its frontend, fix Cloudflare 403
  errors, configure .env credentials, set up Feishu Bitable fields, or
  understand how the two-stage data collection works.
  Also trigger for Chinese phrases: "PH没同步", "飞书没更新", "抓不到数据",
  "重新跑一下周榜", "team members抓不到", "403报错", "选择器失效".
---

# ProductHunt Weekly → Feishu Bitable Sync

**Project repo:** https://github.com/chattingclaire/ProductHunt_WeeklyTops

Automatically scrapes the ProductHunt weekly leaderboard and syncs it into a
Feishu (Lark) Bitable table. Deduplicates by `PH_Id`, enriches records with
team members / follower counts via DrissionPage, and sends an IM notification
after each sync.

---

## How Data Is Collected — Two Stages

Understanding these two stages is essential for debugging or extending the project.

### Stage 1 — ProductHunt Weekly Leaderboard (Apollo SSR JSON)

The weekly leaderboard page (`producthunt.com/leaderboard/weekly/YYYY/WW`)
embeds a full Apollo SSR data snapshot in a `<script>` tag. The script reads
this JSON directly — **no API key or authentication required**.

Fields populated from this source:

| Feishu field | PH source field | Notes |
|---|---|---|
| `Product_Name` | `name` | Product name |
| `Brief` | `tagline` | One-line tagline |
| `Description` | `description` | Full product description |
| `Upvote` | `votesCount` | Weekly upvote count |
| `Launch_tags` | `topics` | Category tags (AI, Productivity, …) |
| `team_members` | `makers[]` | Maker names from leaderboard data |
| `PH_Link` | `url` | Product Hunt product URL |
| `Forum` | derived | Link to PH discussion thread |
| `PH_Id` | `id` | Unique product ID — used for deduplication |
| `Week_Range` | computed | ISO week, e.g. `2025-W44` |
| `Last_Updated` | computed | Timestamp of this sync run |

### Stage 2 — Individual Product Pages (DrissionPage)

Three fields are **not available** in the leaderboard data. The script opens
each product page in a real Chromium browser (via DrissionPage) and scrapes them.

| Feishu field | Where scraped | Notes |
|---|---|---|
| `Followers` | Product main page | Follower count, e.g. `5.2K` |
| `Company_Info` | Product main page → Company Info sidebar | Official website URL |
| `team_members` *(enriched)* | `/makers` sub-page | Full team list; replaces the Stage 1 value if richer |

> `scrape_team_drission.py` can re-run Stage 2 independently on existing
> Bitable records at any time.

---

## Quick Start

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# → edit .env with your credentials (see Configuration section)

python wokflow.py --once          # run immediately
```

---

## Configuration — .env Variables

| Variable | Required | Description |
|---|---|---|
| `FEISHU_APP_ID` | Yes | Feishu / Lark app ID |
| `FEISHU_APP_SECRET` | Yes | Feishu / Lark app secret |
| `FEISHU_TABLE_APP_ID` | Yes | Bitable app token (starts with `BAS…`) |
| `FEISHU_TABLE_ID` | Yes | Table ID inside the Bitable |
| `FEISHU_RECEIVER_OPEN_ID` | Yes | Open ID of the IM notification recipient |
| `PH_COOKIES` | Recommended | Cookie string to bypass Cloudflare 403 |
| `PH_WEEKLY_URL` | No | Override weekly URL; omit to auto-compute |
| `PH_WEEK_OFFSET` | No | Week offset from today: `-1` = last week |
| `PH_BEARER_TOKEN` | No | Legacy fallback — not needed in most cases |
| `TIMEZONE` | No | Default `Asia/Shanghai` |
| `ENABLE_TEAM_SCRAPER` | No | `true` = run team scraper after main sync |
| `http_proxy` / `https_proxy` | No | Proxy URL, e.g. `http://127.0.0.1:7890` |

### How to get PH Cookies

1. Open producthunt.com in Chrome and log in
2. `F12` → **Application** → **Cookies** → `https://www.producthunt.com`
3. Copy all cookies as `key1=value1; key2=value2`
4. Paste as `PH_COOKIES=…` in `.env`

Key cookies: `_producthunt_session`, `cf_clearance`, `__cf_bm`

---

## Feishu Bitable — Required Fields

Create these fields in your Bitable table (names are case-sensitive):

| Field name | Type |
|---|---|
| `PH_Id` | Text — **used for deduplication** |
| `Product_Name` | Text |
| `Brief` | Text |
| `Description` | Text |
| `Upvote` | Number |
| `Launch_tags` | Multi-select or Text |
| `team_members` | Text |
| `PH_Link` | URL |
| `Forum` | URL |
| `Followers` | Text |
| `Company_Info` | URL |
| `Week_Range` | Text |
| `Last_Updated` | Text |

---

## Running Commands

```bash
# Run once immediately
python wokflow.py --once

# Start daily scheduler (08:00 Asia/Shanghai)
python wokflow.py

# Fetch a specific week
PH_WEEK_OFFSET=-1 python wokflow.py --once
PH_WEEKLY_URL=https://www.producthunt.com/leaderboard/weekly/2025/10 python wokflow.py --once

# Enrich team members for existing records
python scrape_team_drission.py --dry-run     # preview, no writes
python scrape_team_drission.py --limit 20    # process up to 20 records
python scrape_team_drission.py               # process all

# Re-process records missing data
python scrape_empty_records.py

# Back-fill historical weeks
python update_from_weekly.py
```

---

## Debugging DrissionPage Selectors

PH updates its frontend periodically. When Stage 2 fields stop being scraped,
check whether the page structure still matches the selectors below.

### Followers

Script looks for a `<p>` tag with classes `text-14 font-medium text-gray-700`
containing text like `"5.2K followers"`.

```
Primary selector:  css:p.text-14.font-medium.text-gray-700
Fallback:          regex r"([\d.]+[KkMm]?)\s*followers?" on full page HTML
Code location:     wokflow.py ~line 121 (regex), ~line 837 (selector)
```

**Verify:** Open any PH product page → DevTools → inspect the follower count.
If the `<p>` classes changed, update both the regex constant `FOLLOWERS_P_TAG_RE`
and the CSS selector in `scrape_product_page_with_drission()`.

---

### Company Info

Script finds the "Company Info" heading, then grabs the adjacent external link.

```
Step 1 — heading:  text:Company Info
Step 2 — link:     css:a[class*="stroke-gray-900"][target="_blank"]
Code location:     wokflow.py ~line 864, scrape_team_drission.py ~line 277
```

**Verify:** Open a product page that has a website → DevTools → find the
"Company Info" sidebar. Check that the heading text is still exactly
`"Company Info"` and the website `<a>` still has `stroke-gray-900` in its class.

---

### Team Members

Script navigates to the `/makers` sub-page then extracts member profile links.

```
Step 1 — find nav:   css:a[href$="/makers"]
         or via:     text:More → a[href$="/makers"]
Step 2 — members:    css:a[href^="/@"].font-semibold
Fallback:            css:a[href^="/@"]
Code location:       wokflow.py ~line 885 (nav), ~line 924 (members)
                     scrape_team_drission.py ~line 299 (nav), ~line 425 (members)
```

**Verify:** Open `producthunt.com/products/<slug>/makers` → DevTools → inspect
team member name links. They should be `<a href="/@username">` with class
`font-semibold`. If the class changed, update both files at the lines above.

---

## Common Errors

| Error | Fix |
|---|---|
| Cloudflare 403 / challenge page | Add `PH_COOKIES` to `.env`; make sure `cf_clearance` is fresh |
| `Field X not found in Feishu table` | Create the missing field; field names are case-sensitive |
| Feishu token / auth error | Verify `FEISHU_APP_ID`/`FEISHU_APP_SECRET`; app needs Bitable + Message permissions |
| Records not deduplicating | Confirm `PH_Id` field exists in your table |
| DrissionPage can't find Chrome | Install Chrome locally |
| `team_members` empty after sync | PH page structure may have changed — run selector verification above |
| Stage 1 returns no products | Weekly URL may be wrong; check `PH_WEEKLY_URL` or `PH_WEEK_OFFSET` |

---

## Project File Map

```
wokflow.py                 # main workflow: Stage 1 + Stage 2 + Feishu sync
scrape_team_drission.py    # standalone Stage 2: team member enrichment
scrape_empty_records.py    # re-process records missing fields
update_from_weekly.py      # back-fill historical weekly data
import_team_members.py     # import team data from local JSON
requirements.txt           # Python dependencies
.env.example               # credential template — copy to .env
.claude/skill/SKILL.md     # this skill's source
producthunt-feishu-sync.skill  # packaged skill file (install with Claude Code)
```

---

## Installing This Skill

```bash
# from the project directory after cloning:
claude skill install producthunt-feishu-sync.skill
```

Once installed, Claude will automatically use this skill whenever you describe
a ProductHunt sync, Feishu Bitable setup, or DrissionPage debugging task —
in any language.
