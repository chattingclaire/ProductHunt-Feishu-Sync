---
name: producthunt-feishu-sync
description: >
  Executable agent skill: scrape the ProductHunt weekly leaderboard and sync it
  into a Feishu (Lark) Bitable table using the bundled Python scripts.
  Use this skill whenever the user wants to: run or automate the PH weekly sync,
  set up the PH→Feishu pipeline from scratch, enrich Bitable records with
  team members / follower counts, debug DrissionPage selectors when PH updates
  its frontend, fix Cloudflare 403 errors, or configure credentials.
  Also trigger for: "PH没同步", "飞书没更新", "抓不到数据",
  "重新跑一下周榜", "team members抓不到", "403报错", "选择器失效".
  The bundled scripts in scripts/ do all the real work — Claude's job is to
  set up credentials, run the scripts, and handle errors.
---

# ProductHunt Weekly → Feishu Bitable Sync

**Project repo:** https://github.com/chattingclaire/ProductHunt-Feishu-Sync

Scrapes any ProductHunt leaderboard (weekly by default) and syncs every product
into a Feishu (Lark) Bitable table — auto-dedup by `PH_Id`, team enrichment,
and IM notification after each sync.

---

## Agent Instructions — How to Use This Skill

When this skill is triggered, follow these steps:

### 1. Locate the scripts

```
SKILL_DIR=~/.claude/skills/producthunt-feishu-sync/scripts
```

All Python scripts are bundled here after `claude skill install`.

### 2. Check / set up credentials

Check if `$SKILL_DIR/.env` exists and is filled in.
If not, copy the template and ask the user to fill in the values:

```bash
cp $SKILL_DIR/.env.example $SKILL_DIR/.env
# then edit .env with user's credentials
```

Required variables:

| Variable | Where to get it |
|---|---|
| `FEISHU_APP_ID` | Feishu developer console → app → Credentials |
| `FEISHU_APP_SECRET` | same |
| `FEISHU_TABLE_APP_ID` | Bitable URL → `BAS…` segment |
| `FEISHU_TABLE_ID` | Bitable URL → `tbl…` segment |
| `FEISHU_RECEIVER_OPEN_ID` | Open ID of the IM notification recipient |
| `PH_COOKIES` | Chrome → F12 → Application → Cookies → copy all as `key=val; key=val` |

### 3. Install Python dependencies (first run only)

```bash
cd $SKILL_DIR
pip install -r requirements.txt
```

### 4. Run the sync

```bash
cd $SKILL_DIR
python wokflow.py --once          # run immediately
python wokflow.py                 # start daily scheduler (08:00 Asia/Shanghai)
```

Other useful commands:

```bash
# Different leaderboards
PH_WEEK_OFFSET=-1 python wokflow.py --once          # last week
PH_WEEKLY_URL=https://www.producthunt.com/leaderboard/weekly/2025/10 python wokflow.py --once

# Enrich team members for existing records
python scrape_team_drission.py --dry-run   # preview only
python scrape_team_drission.py --limit 20  # process up to 20
python scrape_team_drission.py             # process all

# Fix records missing fields
python scrape_empty_records.py

# Back-fill historical weeks
python update_from_weekly.py
```

### 5. Handle errors

See the **Common Errors** section below.

---

## Feishu Bitable — Required Fields

Create these 13 fields before first run (names are **case-sensitive**).
Download the template from the repo: `assets/feishu_bitable_template.xlsx`
and import it — all field names are pre-set. Then manually change types:

| Field | Type |
|---|---|
| `PH_Id` | Text — used for deduplication |
| `Product_Name` | Text |
| `Brief` | Text |
| `Description` | Text |
| `Upvote` | **Number** |
| `Launch_tags` | **Multi-select** |
| `team_members` | Text |
| `PH_Link` | **URL** |
| `Forum` | **URL** |
| `Followers` | Text |
| `Company_Info` | **URL** |
| `Week_Range` | Text |
| `Last_Updated` | Text |

---

## How Data Is Collected — Two Stages

### Stage 1 — Leaderboard page (Apollo SSR JSON)

PH embeds a full data snapshot in each leaderboard page. Read directly — no API key needed.

Fields: `Product_Name` · `Brief` · `Description` · `Upvote` · `Launch_tags` · `team_members` · `PH_Link` · `Forum` · `PH_Id` · `Week_Range`

### Stage 2 — Per-product pages (DrissionPage / real Chromium)

Three fields aren't in the leaderboard data — scraped via real browser:

Fields: `Followers` · `Company_Info` · `team_members` (enriched from `/makers`)

---

## Debugging DrissionPage Selectors

PH updates its frontend periodically. When Stage 2 fields stop being scraped:

### Followers
```
Selector:   css:p.text-14.font-medium.text-gray-700
Fallback:   regex r"([\d.]+[KkMm]?)\s*followers?" on full HTML
Location:   wokflow.py ~line 121 (regex), ~line 837 (selector)
```

### Company Info
```
Step 1:  text:Company Info   (find heading)
Step 2:  css:a[class*="stroke-gray-900"][target="_blank"]
Location: wokflow.py ~line 864, scrape_team_drission.py ~line 277
```

### Team Members
```
Step 1:  css:a[href$="/makers"]  (or text:More → dropdown)
Step 2:  css:a[href^="/@"].font-semibold
Fallback: css:a[href^="/@"]
Location: wokflow.py ~line 885 (nav), ~line 924 (members)
         scrape_team_drission.py ~line 299 (nav), ~line 425 (members)
```

---

## Common Errors

| Error | Fix |
|---|---|
| Cloudflare 403 / challenge page | Add fresh `PH_COOKIES` to `.env`; must include `cf_clearance` |
| `Field X not found in Feishu table` | Create the missing field — names are case-sensitive |
| Feishu token / auth error | Check `FEISHU_APP_ID`/`FEISHU_APP_SECRET`; enable Bitable + Message permissions |
| Records not deduplicating | Confirm `PH_Id` field exists |
| DrissionPage can't find Chrome | Install Google Chrome locally |
| `team_members` empty after sync | PH page structure may have changed — check selectors above |
| Stage 1 returns no products | Check `PH_WEEKLY_URL` or `PH_WEEK_OFFSET` |

---

## Bundled Scripts

```
scripts/wokflow.py               # main: Stage 1 + Stage 2 + Feishu sync
scripts/scrape_team_drission.py  # standalone Stage 2: team member enrichment
scripts/scrape_empty_records.py  # re-process records missing fields
scripts/update_from_weekly.py    # back-fill historical weekly data
scripts/requirements.txt         # Python dependencies
scripts/.env.example             # credential template
```
