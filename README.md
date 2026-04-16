# ProductHunt Weekly Tops → Feishu Bitable Sync

Automatically scrape the **ProductHunt weekly leaderboard** and sync it to a **Feishu (Lark) Bitable** table — with deduplication, team-member enrichment, and IM notifications.

## Preview

**View 1 — Core fields** (product name, upvotes, tags, Chinese description, team members, company info, PH link):

![Feishu Bitable - Core Fields](assets/demo1.png)

**View 2 — Extended fields** (brief, Chinese summary, full description, followers, forum link, PH ID, last updated, week range):

![Feishu Bitable - Extended Fields](assets/demo2.png)

---

## Features

- **Auto-sync** — runs daily at 08:00 (Asia/Shanghai) via APScheduler; or run once on demand
- **Cloudflare bypass** — uses [DrissionPage](https://github.com/g1879/DrissionPage) (real Chromium) to handle JS challenges
- **Apollo SSR parsing** — extracts structured product data directly from ProductHunt's internal Apollo cache
- **Feishu Bitable integration** — creates new records or updates existing ones, deduplicated by `PH_Id`
- **Team member scraper** — separate script to enrich records with founder / team info by clicking through product pages
- **IM notification** — sends a Feishu chat message when each sync completes
- **Proxy support** — respects `http_proxy` / `https_proxy` / `all_proxy` env vars

---

## Architecture

```
ProductHunt weekly page
        │
        ▼ DrissionPage (Chromium, bypasses Cloudflare)
  Apollo SSR JSON
        │
        ▼ parse fields
  [name, tagline, votes, URL, makers, ...]
        │
        ├──▶ Feishu Bitable  (upsert by PH_Id)
        │
        └──▶ Feishu IM notification
             (sent after every sync)

(optional) scrape_team_drission.py
        │
        ▼ DrissionPage (click "Team" tab)
  team member names
        │
        └──▶ Feishu Bitable  (update team_members field)
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.9+ |
| Chrome / Chromium | installed locally |
| Feishu (Lark) developer app | with Bitable & IM permissions |
| ProductHunt account | optional (cookies help bypass 403) |

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/chattingclaire/ProductHunt_WeeklyTops.git
cd ProductHunt_WeeklyTops

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# then edit .env with your credentials
```

| Variable | Required | Description |
|---|---|---|
| `FEISHU_APP_ID` | Yes | Feishu / Lark app ID |
| `FEISHU_APP_SECRET` | Yes | Feishu / Lark app secret |
| `FEISHU_TABLE_APP_ID` | Yes | Bitable app token (starts with `BAS...`) |
| `FEISHU_TABLE_ID` | Yes | Table ID inside the Bitable |
| `FEISHU_RECEIVER_OPEN_ID` | Yes | Open ID of the IM notification recipient |
| `PH_WEEKLY_URL` | No | Override the weekly URL; omit to auto-compute |
| `PH_WEEK_OFFSET` | No | Integer offset from current week (`-1` = last week) |
| `PH_BEARER_TOKEN` | No | ProductHunt Bearer token (fallback only) |
| `PH_COOKIES` | No | Cookie string — strongly recommended to avoid 403 |
| `TIMEZONE` | No | Default `Asia/Shanghai` |
| `ENABLE_TEAM_SCRAPER` | No | Set `true` to run team scraper after main sync |
| `http_proxy` | No | HTTP proxy (e.g. `http://127.0.0.1:7890`) |
| `https_proxy` | No | HTTPS proxy |

### 3. Get ProductHunt cookies (recommended)

Cookies let DrissionPage bypass Cloudflare rate limits:

1. Open [producthunt.com](https://www.producthunt.com) in Chrome and log in
2. Press `F12` → **Application** tab → **Cookies** → `https://www.producthunt.com`
3. Copy all cookies in the format `key1=value1; key2=value2`
4. Paste as `PH_COOKIES=...` in your `.env`

Key cookies to look for: `_producthunt_session`, `cf_clearance`, `__cf_bm`

### 4. Set up Feishu Bitable

Your Bitable table should have (at minimum) these fields:

| Field name | Type | Notes |
|---|---|---|
| `PH_Id` | Text | Unique product ID — used for deduplication |
| `Name` | Text | Product name |
| `Tagline` | Text | One-line description |
| `Votes` | Number | Upvote count |
| `URL` | URL | Product Hunt link |
| `Week` | Text | ISO week string, e.g. `2025-W44` |
| `team_members` | Text | Populated by team scraper (optional) |

---

## Usage

### Run once immediately

```bash
python wokflow.py --once
```

### Start the daily scheduler (08:00 Asia/Shanghai)

```bash
python wokflow.py
```

### Scrape team members for existing records

```bash
# Dry run — print results without writing to Feishu
python scrape_team_drission.py --dry-run

# Process up to 20 records with empty team_members
python scrape_team_drission.py --limit 20

# Process all
python scrape_team_drission.py
```

### Fetch a specific week

```bash
PH_WEEK_OFFSET=-1 python wokflow.py --once   # last week
PH_WEEKLY_URL=https://www.producthunt.com/leaderboard/weekly/2025/10 python wokflow.py --once
```

---

## Project Structure

```
.
├── wokflow.py                # Main workflow: fetch PH → sync Feishu
├── scrape_team_drission.py   # Team member enrichment (DrissionPage)
├── scrape_team_members.py    # Team member enrichment (Playwright variant)
├── scrape_empty_records.py   # Re-process records missing data
├── update_from_weekly.py     # Utility to back-fill weekly data
├── import_team_members.py    # Import team data from local JSON
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
└── debug_*/                  # Debug scripts (not needed in production)
```

---

## Dependencies

```
requests
APScheduler
python-dotenv
pytz
DrissionPage>=4.0.0
playwright>=1.40.0   # optional Playwright variant
```

---

## Troubleshooting

**Cloudflare 403 / challenge loop**
→ Add `PH_COOKIES` to `.env`. Make sure `cf_clearance` is included and fresh.

**DrissionPage can't find Chrome**
→ Install Chrome, or set `CHROMIUM_PATH` to your browser binary.

**Feishu token error**
→ Verify `FEISHU_APP_ID` / `FEISHU_APP_SECRET` and that the app has *Bitable* and *Message* permissions.

**Records not deduplicating**
→ Check that `PH_Id` field exists in your table and contains the correct product IDs.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

PRs and issues welcome! If ProductHunt changes its page structure and parsing breaks, please open an issue with the new HTML snippet.
