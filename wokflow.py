#!/usr/bin/env python3
"""
ProductHunt Weekly Leaderboard → Feishu Bitable sync

Features:
- Runs daily at 08:00 Asia/Shanghai (when launched normally)
- Fetches the ProductHunt weekly leaderboard page (via the weekly URL)
- Maps fields to Feishu Bitable fields
- De-duplicates by PH_Id: create new records, update existing ones
- Sends a Feishu IM notification after sync

Configuration via environment variables (recommended to place a .env file next to this script):
  PH_BEARER_TOKEN              ProductHunt GraphQL Bearer (optional, used as fallback)
  PH_WEEKLY_URL                Weekly leaderboard URL, e.g. https://www.producthunt.com/leaderboard/weekly/2025/44
  FEISHU_APP_ID                Feishu App ID
  FEISHU_APP_SECRET            Feishu App Secret
  FEISHU_TABLE_APP_ID          Feishu Bitable App Token
  FEISHU_TABLE_ID              Feishu Bitable Table ID
  FEISHU_RECEIVER_OPEN_ID      Feishu Open ID to notify
  TIMEZONE                     Default Asia/Shanghai
  ENABLE_TEAM_SCRAPER          Set to 'true' to enable team member scraper after sync

Usage:
  python wokflow.py              # start scheduler (08:00 daily)
  python wokflow.py --once       # run once immediately
"""

import argparse
import atexit
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import pytz
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import time

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

# try:
#     from playwright.sync_api import sync_playwright, Browser, Page
#     PLAYWRIGHT_AVAILABLE = True
# except ImportError:
PLAYWRIGHT_AVAILABLE = False
Browser = None
Page = None


# ---------- Configuration helpers ----------

def load_config() -> Dict[str, str]:
    if load_dotenv is not None:
        # load .env if present in the same directory
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    # Set proxy from environment (no defaults, proxy is optional)
    proxy_http = os.getenv("http_proxy") or os.getenv("HTTP_PROXY") or None
    proxy_https = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or None
    proxy_all = os.getenv("all_proxy") or os.getenv("ALL_PROXY") or None
    
    return {
        "PH_BEARER_TOKEN": os.getenv("PH_BEARER_TOKEN", ""),
        "PH_WEEKLY_URL": os.getenv("PH_WEEKLY_URL", "auto"),
        "PH_WEEK_OFFSET": os.getenv("PH_WEEK_OFFSET", "0"),
        "PH_COOKIES": os.getenv("PH_COOKIES", ""),  # Cookies string like "key1=value1; key2=value2"
        "PROXY_HTTP": proxy_http,
        "PROXY_HTTPS": proxy_https,
        "PROXY_ALL": proxy_all,
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET", ""),
        "FEISHU_TABLE_APP_ID": os.getenv("FEISHU_TABLE_APP_ID", ""),
        "FEISHU_TABLE_ID": os.getenv("FEISHU_TABLE_ID", ""),
        "FEISHU_RECEIVER_OPEN_ID": os.getenv("FEISHU_RECEIVER_OPEN_ID", ""),
        "TIMEZONE": os.getenv("TIMEZONE", "Asia/Shanghai"),
        "ENABLE_TEAM_SCRAPER": os.getenv("ENABLE_TEAM_SCRAPER", "false").lower() == "true",
    }


def now_cn_str(tz_name: str) -> str:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def compute_weekly_url(tz_name: str, week_offset: int = 0) -> str:
    """Compute ProductHunt weekly leaderboard URL for the ISO week.

    week_offset allows fetching previous/next week (e.g., -1 for previous week).
    """
    tz = pytz.timezone(tz_name)
    today = datetime.now(tz).date()

    # Find Monday of current ISO week
    iso_weekday = today.isoweekday()  # 1=Mon..7=Sun
    monday = today if iso_weekday == 1 else (today - timedelta(days=iso_weekday - 1))

    # Apply week offset in 7-day jumps
    monday = monday + timedelta(days=7 * week_offset)

    # Now recompute ISO year/week from that Monday
    iso_year, iso_week, _ = monday.isocalendar()
    return f"https://www.producthunt.com/leaderboard/weekly/{iso_year}/{int(iso_week)}"


# ---------- ProductHunt weekly fetch ----------

NEXT_DATA_RE = re.compile(r"<script id=__NEXT_DATA__ type=\"application/json\">(.*?)</script>", re.S)
# Regex for Apollo SSR data
APOLLO_DATA_RE = re.compile(r'Symbol\.for\("ApolloSSRDataTransport"\).*?\.push\((.*)', re.S)
# Match followers in <p> tag: <p class="...">798 followers</p>
FOLLOWERS_P_TAG_RE = re.compile(r"<p[^>]*class=\"[^\"]*text-14[^\"]*font-medium[^\"]*text-gray-700[^\"]*\">([0-9,\.]+[Kk]?)\s*followers</p>", re.I)
# Fallback: match any text pattern like "798 followers" or "20K followers"
FOLLOWERS_TEXT_RE = re.compile(r"([0-9][0-9,\.]*\s*[Kk]?)\s*followers", re.I)
# Match Company Info: find "Company Info" text, then extract first <a href="..."> after it
COMPANY_INFO_RE = re.compile(r"Company Info[^<]*</div>[^<]*<a[^>]*href=\"([^\"]+)\"", re.I | re.S)
# Match Brief/tagline: usually in <h2> tag after product name, like <h2 class="text-18 text-gray-700">Turn entire websites into LLM-ready data</h2>
BRIEF_TAG_RE = re.compile(r"<h2[^>]*class=\"[^\"]*text-18[^\"]*text-gray-700[^\"]*\">([^<]+)</h2>", re.I)
# Match team members: find "Team Members" heading, then extract all <img alt="Name"> in the grid container
TEAM_MEMBERS_RE = re.compile(r"Team Members[^<]*</p>[^<]*<div[^>]*class=\"[^\"]*grid[^\"]*\"[^>]*>(.*?)</div>", re.I | re.S)
TEAM_MEMBER_NAME_RE = re.compile(r"<img[^>]*alt=\"([^\"]+)\"[^>]*class=\"rounded-full\"", re.I)
SIMILAR_LINK_RE = re.compile(r"/products/([\w-]+)\"[^>]*>\s*<span[^>]*>\s*([^<]+)\s*<", re.I)


from DrissionPage import ChromiumPage, ChromiumOptions

def fetch_weekly_page(url: str, session: Optional[requests.Session] = None) -> dict:
    print(f"[INFO] Fetching weekly page via DrissionPage: {url}")
    
    co = ChromiumOptions()
    # co.headless()
    page = ChromiumPage(addr_or_opts=co)
    
    try:
        page.get(url)
        # Wait for potential Cloudflare challenge or page load
        page.wait(5)
        
        # Check if we are stuck on Cloudflare (English or Chinese)
        if any(txt in page.title for txt in ["Just a moment", "Cloudflare", "请稍候", "请稍后"]):
            print(f"[INFO] Cloudflare challenge detected ({page.title}), waiting longer...")
            page.wait(20)
            
        print(f"[DEBUG] Page Title: {page.title}")
        
        html = page.html
        
        # Try Apollo data first (newer PH)
        m_apollo = APOLLO_DATA_RE.search(html)
        if m_apollo:
            print("[INFO] Found Apollo SSR data")
            try:
                json_str = m_apollo.group(1).replace("undefined", "null")
                data, _ = json.JSONDecoder().raw_decode(json_str)
                return data
            except json.JSONDecodeError as e:
                print(f"[WARN] Failed to parse Apollo JSON: {e}")
                print(f"[DEBUG] JSON Start: {json_str[:100]}")
                print(f"[DEBUG] JSON End: {json_str[-100:]}")

        # Fallback to Next.js data
        m = NEXT_DATA_RE.search(html)
        if not m:
            # Try waiting a bit more if not found immediately
            print("[INFO] Data script not found immediately, waiting more...")
            page.wait(5)
            html = page.html
            m_apollo = APOLLO_DATA_RE.search(html)
            if m_apollo:
                print("[INFO] Found Apollo SSR data after wait")
                try:
                    json_str = m_apollo.group(1).replace("undefined", "null")
                    data, _ = json.JSONDecoder().raw_decode(json_str)
                    return data
                except json.JSONDecodeError as e:
                    print(f"[WARN] Failed to parse Apollo JSON: {e}")
                    print(f"[DEBUG] JSON Start: {json_str[:100]}")
                
            m = NEXT_DATA_RE.search(html)
            
        if not m:
            # Debug: save html to file
            with open("debug_weekly_fail.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[INFO] Saved failed HTML to debug_weekly_fail.html")
            raise RuntimeError("Failed to locate __NEXT_DATA__ or Apollo data on ProductHunt weekly page")
            
        data = json.loads(m.group(1))
        return data
    finally:
        try:
            page.quit()
        except:
            pass


def parse_weekly_products(data: dict) -> List[dict]:
    # The structure is subject to change; we try multiple likely paths.
    # We aim to extract id, name, tagline, description, votesCount, commentsCount, url, website, makers, topics.
    candidates = []
    
    # Check for Apollo data structure
    if "rehydrate" in data:
        print("[DEBUG] Parsing Apollo data structure")
        rehydrate = data["rehydrate"]
        for key, val in rehydrate.items():
            # We look for objects that contain "homefeedItems"
            if val and "data" in val and val["data"] and "homefeedItems" in val["data"]:
                edges = val["data"]["homefeedItems"].get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    if node.get("__typename") == "Post":
                        # Map Apollo Post to our candidate format
                        prod = node.get("product", {})
                        candidate = {
                            "id": node.get("id"),
                            "name": node.get("name"),
                            "tagline": node.get("tagline"),
                            "slug": node.get("slug"),
                            "votesCount": node.get("latestScore"),
                            "commentsCount": node.get("commentsCount"),
                            "url": f"https://www.producthunt.com/posts/{node.get('slug')}",
                            "website": prod.get("websiteUrl"), # Might not be here, check product node
                            "topics": node.get("topics", {}).get("edges", []),
                            "description": node.get("description"),
                            # Store raw node for further extraction if needed
                            "_raw": node
                        }
                        candidates.append(candidate)

    # Try a few known places in PH's Next.js data (Legacy)
    def deep_get(obj, path, default=None):
        cur = obj
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return default
        return cur

    # 1) Newer PH design packs data under props/pageProps
    page_props = deep_get(data, ["props", "pageProps"]) or {}
    
    # Collect any arrays of nodes that look like products (recursive search for legacy/Next.js structure)
    def collect_nodes(obj):
        if isinstance(obj, list):
            for x in obj:
                collect_nodes(x)
        elif isinstance(obj, dict):
            # heuristics: node-like dict containing name and id and votes
            keys = set(obj.keys())
            if {"id", "name"}.issubset(keys):
                candidates.append(obj)
            for v in obj.values():
                collect_nodes(v)

    if not candidates:
        collect_nodes(page_props)

    products = []
    for node in candidates:
        # Normalize data
        p_id = node.get("id") or node.get("legacyId") or node.get("slug") or ""
        p_name = node.get("name") or ""
        p_tagline = node.get("tagline") or node.get("subtitle") or ""
        p_desc = node.get("description") or ""
        p_votes = node.get("votesCount") or node.get("votes") or node.get("latestScore") or 0
        p_comments = node.get("commentsCount") or 0
        
        # URL
        p_url = node.get("url") or node.get("redirectUrl") or ""
        if not p_url and node.get("slug"):
             p_url = f"https://www.producthunt.com/posts/{node.get('slug')}"
             
        p_website = node.get("website") or node.get("websiteUrl") or ""
        
        # Makers
        p_makers = []
        makers_raw = node.get("makers") or []
        if isinstance(makers_raw, list):
            p_makers = [m.get("name") for m in makers_raw if isinstance(m, dict) and m.get("name")]
            
        # Topics
        p_topics = []
        topics_raw = node.get("topics") or []
        if isinstance(topics_raw, list):
            # Check if it's a list of edges (Apollo) or list of topics (Legacy)
            if topics_raw and "node" in topics_raw[0]:
                 # Apollo list of edges
                 p_topics = [t.get("node", {}).get("name") for t in topics_raw if isinstance(t, dict) and t.get("node", {}).get("name")]
            else:
                 # Legacy list of dicts
                 p_topics = [t.get("name") for t in topics_raw if isinstance(t, dict) and t.get("name")]
        elif isinstance(topics_raw, dict) and isinstance(topics_raw.get("edges"), list):
            # Apollo/Relay edges format (if passed as dict)
            p_topics = [edge.get("node", {}).get("name") for edge in topics_raw["edges"] if edge.get("node", {}).get("name")]

        product = {
            "id": p_id,
            "name": p_name,
            "tagline": p_tagline,
            "description": p_desc,
            "votesCount": p_votes,
            "commentsCount": p_comments,
            "url": p_url,
            "website": p_website,
            "makers": p_makers,
            "topics": p_topics,
        }
        products.append(product)

    # de-duplicate by id keeping highest votes
    by_id: Dict[str, dict] = {}
    for p in products:
        pid = str(p.get("id") or "")
        if not pid:
            continue
        old = by_id.get(pid)
        if (old is None) or (p.get("votesCount", 0) > old.get("votesCount", 0)):
            by_id[pid] = p
    return list(by_id.values())


def augment_from_weekly_page(weekly_url: str, products: List[dict], session: Optional[requests.Session] = None) -> List[dict]:
    """Try to fill missing fields (tagline/website/makers/topics) using weekly page data.

    Non-fatal: if the page fetch fails (e.g., 403), just return the original input.
    """
    try:
        data = fetch_weekly_page(weekly_url, session=session)
        page_products = parse_weekly_products(data)
    except Exception:
        return products

    # Build indexes by id and by url for best-effort matching
    by_id = {str(p.get("id")): p for p in page_products if p.get("id")}
    by_url = {p.get("url"): p for p in page_products if p.get("url")}

    out: List[dict] = []
    for n in products:
        m = by_id.get(str(n.get("id"))) or by_url.get(n.get("url"))
        if not m:
            out.append(n)
            continue
        merged = dict(n)
        if not merged.get("tagline") and m.get("tagline"):
            merged["tagline"] = m.get("tagline")
        if not merged.get("website") and m.get("website"):
            merged["website"] = m.get("website")
        if (not merged.get("makers")) and m.get("makers"):
            merged["makers"] = m.get("makers")
        if (not merged.get("topics")) and m.get("topics"):
            merged["topics"] = m.get("topics")
        out.append(merged)
    return out


def extract_slug_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    # Support both /products/<slug> and /posts/<slug>
    m = re.search(r"/(?:products|posts)/([\w-]+)", url)
    return m.group(1) if m else None


def create_ph_session(cookies_str: str = "", proxy_config: Optional[Dict[str, str]] = None) -> requests.Session:
    """Create a requests Session with Product Hunt cookies. Always fetches fresh cookies from homepage."""
    session = requests.Session()
    
    # Configure proxy (only if provided and not None)
    if proxy_config:
        proxy_http = proxy_config.get("PROXY_HTTP")
        proxy_https = proxy_config.get("PROXY_HTTPS")
        if proxy_http or proxy_https:
            proxies = {
                "http": proxy_http,
                "https": proxy_https,
            }
            session.proxies = proxies
            print(f"[DEBUG] Using proxy: {proxy_http or proxy_https}")
    
    # Set headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.producthunt.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    # Add initial cookies if provided (for authentication)
    if cookies_str:
        cookies_str = cookies_str.strip()
        headers["Cookie"] = cookies_str
        print(f"[DEBUG] Added initial Cookie header with {len(cookies_str.split(';'))} cookies")
    session.headers.update(headers)
    
    # Always visit homepage first to get fresh cf_clearance and __cf_bm cookies
    try:
        resp = session.get("https://www.producthunt.com/", timeout=15)
        if resp.status_code == 200:
            # Extract fresh cookies from response
            fresh_cookies = []
            for cookie in session.cookies:
                if cookie.name in ("cf_clearance", "__cf_bm"):
                    fresh_cookies.append(f"{cookie.name}={cookie.value}")
            if fresh_cookies:
                print(f"[DEBUG] Got fresh cookies from homepage: {', '.join([c.split('=')[0] for c in fresh_cookies])}")
            else:
                print(f"[DEBUG] Homepage accessed but no fresh cookies found")
        else:
            print(f"[DEBUG] Homepage returned {resp.status_code}")
    except Exception as e:
        print(f"[DEBUG] Failed to access homepage: {e}")
    
    return session


# Global session for reuse (will be initialized in run_sync)
_ph_session: Optional[requests.Session] = None

# Global Playwright browser instance
_playwright_browser: Optional[Browser] = None
_playwright_context: Optional[object] = None
_playwright_pw: Optional[object] = None


def init_playwright_browser(proxy_config: Optional[Dict[str, str]] = None) -> bool:
    """Initialize Playwright browser if available. Returns True if successful."""
    global _playwright_browser, _playwright_context, _playwright_pw
    if not PLAYWRIGHT_AVAILABLE:
        print("[WARN] Playwright not available. Install with: pip install playwright && playwright install chromium")
        return False
    if _playwright_browser is not None:
        return True  # Already initialized
    try:
        _playwright_pw = sync_playwright().start()
        
        # Configure proxy if provided or from environment
        launch_options = {"headless": True}
        context_options = {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": {"width": 1920, "height": 1080},
        }
        
        # Get proxy from config or environment
        proxy_http = None
        if proxy_config:
            proxy_http = proxy_config.get("PROXY_HTTP") or proxy_config.get("PROXY_HTTPS")
        if not proxy_http:
            # Try environment variables
            proxy_http = os.getenv("http_proxy") or os.getenv("HTTP_PROXY") or os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")
        
        if proxy_http:
            # Extract proxy server from URL (e.g., "http://127.0.0.1:7890")
            if proxy_http.startswith("http://") or proxy_http.startswith("https://"):
                proxy_url = proxy_http
            elif proxy_http.startswith("socks5://"):
                proxy_url = proxy_http
            else:
                proxy_url = f"http://{proxy_http}"
            # Parse proxy URL
            from urllib.parse import urlparse
            parsed = urlparse(proxy_url)
            proxy_server = f"{parsed.scheme}://{parsed.netloc}"
            launch_options["proxy"] = {"server": proxy_server}
            context_options["proxy"] = {"server": proxy_server}
            print(f"[DEBUG] Playwright using proxy: {proxy_server}")
        
        _playwright_browser = _playwright_pw.chromium.launch(**launch_options)
        _playwright_context = _playwright_browser.new_context(**context_options)
        print("[DEBUG] Playwright browser initialized")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to initialize Playwright browser: {e}")
        return False


def close_playwright_browser() -> None:
    """Close Playwright browser if open."""
    global _playwright_browser, _playwright_context, _playwright_pw
    try:
        if _playwright_context:
            _playwright_context.close()
            _playwright_context = None
        if _playwright_browser:
            _playwright_browser.close()
            _playwright_browser = None
        if _playwright_pw:
            _playwright_pw.stop()
            _playwright_pw = None
        print("[DEBUG] Playwright browser closed")
    except Exception as e:
        print(f"[WARN] Error closing Playwright browser: {e}")


def fetch_product_page_with_playwright(slug: str) -> Optional[dict]:
    """Fetch product page using Playwright and extract __NEXT_DATA__."""
    if not init_playwright_browser():
        return None
    if _playwright_context is None:
        return None
    # Try /products/ first, then /posts/ if that fails
    for path in ["products", "posts"]:
        try:
            url = f"https://www.producthunt.com/{path}/{slug}"
            page = _playwright_context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait for __NEXT_DATA__ to be available
                page.wait_for_selector("script#__NEXT_DATA__", timeout=10000)
                html = page.content()
                page.close()
                
                if len(html) < 1000:
                    print(f"[DEBUG]   Response too short ({len(html)} chars) for {path}/{slug}, trying next path")
                    continue
                m = NEXT_DATA_RE.search(html)
                if not m:
                    if "__NEXT_DATA__" in html:
                        print(f"[DEBUG]   Found __NEXT_DATA__ but regex didn't match for {path}/{slug}")
                    else:
                        print(f"[DEBUG]   No __NEXT_DATA__ found in HTML for {path}/{slug}")
                    continue
                data = json.loads(m.group(1))
                print(f"[DEBUG]   Successfully fetched data from {path}/{slug} using Playwright")
                return data
            except Exception as e:
                page.close()
                if path == "products":
                    continue  # Try /posts/ if /products/ fails
                print(f"[DEBUG]   Error fetching {path}/{slug} with Playwright: {type(e).__name__}: {e}")
                return None
        except Exception as e:
            print(f"[DEBUG]   Unexpected error for {path}/{slug} with Playwright: {type(e).__name__}: {e}")
            if path == "products":
                continue
            return None
    return None


def fetch_product_page_html_with_playwright(slug: str) -> Optional[str]:
    """Fetch product page HTML using Playwright."""
    if not init_playwright_browser():
        return None
    if _playwright_context is None:
        return None
    # Try /products/ first, then /posts/ if that fails
    for path in ["products", "posts"]:
        try:
            url = f"https://www.producthunt.com/{path}/{slug}"
            page = _playwright_context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                page.close()
                return html
            except Exception as e:
                page.close()
                if path == "products":
                    continue  # Try /posts/ if /products/ fails
                print(f"[DEBUG]   Error fetching HTML for {path}/{slug} with Playwright: {type(e).__name__}: {e}")
                return None
        except Exception as e:
            print(f"[DEBUG]   Unexpected error for {path}/{slug} with Playwright: {type(e).__name__}: {e}")
            if path == "products":
                continue
            return None
    return None


def fetch_product_page(slug: str, session: Optional[requests.Session] = None) -> Optional[dict]:
    """Fetch product page data. Uses Playwright if available, falls back to requests."""
    # Try Playwright first (handles 403 errors better)
    if PLAYWRIGHT_AVAILABLE:
        result = fetch_product_page_with_playwright(slug)
        if result is not None:
            return result
        print(f"[DEBUG]   Playwright failed for {slug}, falling back to requests")
    
    # Fallback to requests
    if session is None:
        session = _ph_session or requests
    # Try /products/ first, then /posts/ if that fails
    for path in ["products", "posts"]:
        try:
            url = f"https://www.producthunt.com/{path}/{slug}"
            if isinstance(session, requests.Session):
                resp = session.get(url, timeout=30)
            else:
                resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text
            if len(html) < 1000:
                print(f"[DEBUG]   Response too short ({len(html)} chars) for {path}/{slug}, trying next path")
                continue
            m = NEXT_DATA_RE.search(html)
            if not m:
                # Try to find if __NEXT_DATA__ exists with different pattern
                if "__NEXT_DATA__" in html:
                    print(f"[DEBUG]   Found __NEXT_DATA__ but regex didn't match for {path}/{slug}")
                else:
                    print(f"[DEBUG]   No __NEXT_DATA__ found in HTML for {path}/{slug}")
                continue
            data = json.loads(m.group(1))
            print(f"[DEBUG]   Successfully fetched data from {path}/{slug}")
            return data
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[DEBUG]   404 for {path}/{slug}, trying next path")
                continue
            print(f"[DEBUG]   HTTP error for {path}/{slug}: {e.response.status_code} - {e}")
            continue
        except json.JSONDecodeError as e:
            print(f"[DEBUG]   JSON decode error for {path}/{slug}: {e}")
            continue
        except Exception as e:
            print(f"[DEBUG]   Unexpected error for {path}/{slug}: {type(e).__name__}: {e}")
            continue
    return None


def fetch_product_page_html(slug: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Fetch product page HTML. Uses Playwright if available, falls back to requests."""
    # Try Playwright first (handles 403 errors better)
    if PLAYWRIGHT_AVAILABLE:
        result = fetch_product_page_html_with_playwright(slug)
        if result is not None:
            return result
        print(f"[DEBUG]   Playwright failed for {slug} HTML, falling back to requests")
    
    # Fallback to requests
    if session is None:
        session = _ph_session or requests
    # Try /products/ first, then /posts/ if that fails
    for path in ["products", "posts"]:
        try:
            url = f"https://www.producthunt.com/{path}/{slug}"
            if isinstance(session, requests.Session):
                resp = session.get(url, timeout=30)
            else:
                resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404 and path == "products":
                continue  # Try /posts/ if /products/ returns 404
            return None
        except Exception:
            if path == "products":
                continue  # Try /posts/ if /products/ fails
            return None
    return None


def parse_followers_and_company(next_data: dict) -> Tuple[Optional[int], Optional[str]]:
    # best-effort search across the JSON tree for followersCount and external url near Company Info
    followers = None
    company_url = None

    def traverse(obj):
        nonlocal followers, company_url
        if isinstance(obj, dict):
            # common keys
            if followers is None and isinstance(obj.get("followersCount"), (int, float)):
                followers = int(obj.get("followersCount"))
            # look for company link; often appears as website or external link in side info
            if company_url is None:
                for key in ("companyUrl", "company", "website", "externalUrl", "url"):
                    v = obj.get(key)
                    if isinstance(v, str) and v.startswith("http"):
                        company_url = v
                        break
            for v in obj.values():
                if followers is not None and company_url is not None:
                    return
                traverse(v)
        elif isinstance(obj, list):
            for v in obj:
                if followers is not None and company_url is not None:
                    return
                traverse(v)

    traverse(next_data)
    return followers, company_url


def parse_team_members_from_next(next_data: dict) -> List[str]:
    names: List[str] = []
    seen = set()

    def traverse(obj):
        if isinstance(obj, dict):
            if "name" in obj and "username" in obj and isinstance(obj["name"], str):
                n = obj["name"].strip()
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
            for v in obj.values():
                traverse(v)
        elif isinstance(obj, list):
            for v in obj:
                traverse(v)

    traverse(next_data)
    return names


def parse_team_members_from_html(html: str) -> List[str]:
    """Extract team member names from HTML by finding "Team Members" section and extracting <img alt="Name">."""
    names: List[str] = []
    # Find the Team Members section
    m = TEAM_MEMBERS_RE.search(html)
    if m:
        grid_content = m.group(1)
        # Extract all names from <img alt="Name"> tags
        for name_match in TEAM_MEMBER_NAME_RE.finditer(grid_content):
            name = name_match.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


def parse_similar_from_next(next_data: dict, self_slug: Optional[str]) -> List[str]:
    names: List[str] = []
    seen = set([self_slug] if self_slug else [])
    current_name = None

    # First, find the current product's name to exclude it
    def find_self(o):
        nonlocal current_name
        if isinstance(o, dict):
            if o.get("slug") == self_slug or (self_slug and str(o.get("id", "")) == self_slug):
                current_name = o.get("name")
                return
            for v in o.values():
                find_self(v)
        elif isinstance(o, list):
            for v in o:
                find_self(v)
    
    if self_slug:
        find_self(next_data)
        if current_name:
            seen.add(current_name)

    def consider(obj):
        nonlocal names
        if not isinstance(obj, dict):
            return
        nm = obj.get("name")
        sl = obj.get("slug") or obj.get("id")
        if isinstance(nm, str) and nm.strip() and nm.strip() not in seen:
            if sl and sl not in seen:
                names.append(nm.strip())
                seen.add(nm.strip())
                seen.add(sl)

    def traverse(o, depth=0):
        if depth > 15:  # Prevent too deep recursion
            return
        if isinstance(o, dict):
            # Look for "similar" or "related" sections
            for key in ("similar", "related", "recommended", "alternatives"):
                val = o.get(key)
                if isinstance(val, list):
                    for it in val:
                        consider(it)
            # Also check for product-like objects with name/slug
            if "name" in o and ("slug" in o or "id" in o):
                consider(o)
            for v in o.values():
                traverse(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                traverse(v, depth + 1)

    traverse(next_data)
    return names[:3]


def scrape_product_page_with_drission(product_url: str, page: ChromiumPage) -> dict:
    """
    Scrape product page using DrissionPage to get Followers, Company_Info, team_members, Similar_Product
    Based on scrape_team_drission.py implementation
    
    Args:
        product_url: ProductHunt product URL
        page: DrissionPage ChromiumPage instance (reused across calls)
    
    Returns:
        dict with keys: followers, company_info, team_members, similar_products
    """
    result = {
        "followers": None,
        "company_info": None,
        "team_members": [],
        "similar_products": []
    }
    
    if not product_url:
        return result
    
    print(f"[DEBUG] Scraping with drission: {product_url}")
    
    try:
        # Navigate to product page
        page.get(product_url, timeout=20)
        page.wait(3)  # Wait for page load
        
        # Check for Cloudflare
        if any(txt in page.title for txt in ["Just a moment", "Cloudflare", "请稍候", "请稍后"]):
            print(f"[INFO]   Cloudflare challenge detected ({page.title}), waiting 20s...")
            page.wait(20)
            if any(txt in page.title for txt in ["Just a moment", "Cloudflare", "请稍候", "请稍后"]):
                 print(f"[WARN]   Still stuck on Cloudflare for {product_url}")
        
        # 1. Extract Followers (from main product page)
        try:
            import re
            followers_str = None
            # Try specific selector first
            try:
                followers_elem = page.ele('css:p.text-14.font-medium.text-gray-700', timeout=2)
                if followers_elem:
                    text = followers_elem.text.strip()
                    m = re.search(r'([\d.]+[KkMm]?)\s*followers?', text, re.I)
                    if m:
                        followers_str = m.group(1).upper()
            except:
                pass
            
            # Fallback: search for text containing "followers"
            if not followers_str:
                import re
                all_text = page.html
                m = re.search(r'([\d.]+[KkMm]?)\s*followers?', all_text, re.I)
                if m:
                    followers_str = m.group(1).upper()
            
            if followers_str:
                result["followers"] = followers_str
                print(f"[DEBUG]   Found followers: {followers_str}")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract followers: {e}")
        
        # 2. Extract Company Info (Website URL) - BEFORE navigating to makers (as in scrape_team_drission.py)
        company_info = ""
        try:
            # Strategy: Find "Company Info" text and get nearby link
            company_header = page.ele('text:Company Info', timeout=2)
            if company_header:
                # Try to find the link container by class substring
                website_link = page.ele('css:a[class*="stroke-gray-900"][target="_blank"]', timeout=2)
                if website_link and website_link.states.is_displayed:
                    company_info = website_link.attr('href')
                    if company_info:
                        # Remove query params like ?ref=producthunt
                        if "?" in company_info:
                            company_info = company_info.split("?")[0]
                        result["company_info"] = company_info
                        print(f"[DEBUG]   Found Company Info URL: {company_info}")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract company info: {e}")
        
        # 3. Extract team members (navigate to /makers page) - based on scrape_team_drission.py
        try:
            makers_url = None
            
            # 1. Check for visible /makers link directly
            try:
                makers_link = page.ele('css:a[href$="/makers"]', timeout=2)
                if makers_link and makers_link.states.is_displayed:
                    makers_url = makers_link.attr('href')
                    print(f"[DEBUG]   Found direct makers link: {makers_url}")
            except:
                pass
                
            # 2. If not found, check "More" menu
            if not makers_url:
                print(f"[DEBUG]   Direct makers link not found, checking 'More' menu...")
                try:
                    more_btns = page.eles('text:More')
                    for btn in more_btns:
                        if btn.states.is_displayed and btn.tag in ['span', 'div', 'button']:
                            btn.click()
                            page.wait(1)
                            
                            # Check for makers link in dropdown
                            try:
                                makers_link = page.ele('css:a[href$="/makers"]', timeout=2)
                                if makers_link and makers_link.states.is_displayed:
                                    makers_url = makers_link.attr('href')
                                    print(f"[DEBUG]   Found makers link in dropdown: {makers_url}")
                                    break
                            except:
                                pass
                except Exception as e:
                    print(f"[DEBUG]   Error checking More menu: {e}")
            
            # 3. Navigate to makers URL if found
            if makers_url:
                if not makers_url.startswith('http'):
                    makers_url = 'https://www.producthunt.com' + makers_url if makers_url.startswith('/') else makers_url
                
                print(f"[INFO]   Navigating to Team page: {makers_url}")
                page.get(makers_url)
                page.wait(3)
                
                # Extract team member names (same logic as scrape_team_drission.py)
                links = page.eles('css:a[href^="/@"].font-semibold')
                print(f"[DEBUG]   Found {len(links)} team member links with font-semibold class")
                
                team_members = []
                seen_hrefs = set()
                
                for link in links:
                    try:
                        href = link.attr('href')
                        text = link.text.strip() if link.text else ""
                        
                        # Filter out non-name text (reviews, votes, etc.)
                        skip_keywords = ['review', 'vote', 'upvote', 'comment', 'follower', 'following']
                        if any(keyword in text.lower() for keyword in skip_keywords):
                            continue
                        
                        # Skip if contains numbers (likely "X reviews", "X votes")
                        if any(char.isdigit() for char in text):
                            continue
                        
                        # Only process each user once (by href)
                        if href and href not in seen_hrefs and text and len(text) > 2:
                            team_members.append(text)
                            seen_hrefs.add(href)
                            print(f"[DEBUG]   Found team member: {text}")
                    except:
                        continue
                
                result["team_members"] = team_members
                print(f"[DEBUG]   Extracted {len(team_members)} team members")
            else:
                print(f"[WARN]   Could not find /makers link")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract team_members: {e}")
        
        # 4. Extract Similar Products (top 3) - navigate back to main page first
        try:
            # Navigate back to main product page if we went to /makers
            if '/makers' in page.url:
                page.get(product_url)
                page.wait(2)
            
            # Look for "Similar Products" section
            # Try to find product links in similar section
            similar_links = page.eles('css:a[href^="/products/"]')
            similar_products = []
            seen_slugs = set()
            
            for link in similar_links:
                try:
                    href = link.attr('href')
                    if href and '/products/' in href:
                        slug = href.split('/products/')[-1].split('?')[0].split('#')[0]
                        # Skip current product
                        if slug and slug not in seen_slugs and slug not in product_url:
                            # Get product name from link text or nearby element
                            text = link.text.strip() if link.text else ""
                            if text and len(text) > 2:
                                similar_products.append(text)
                                seen_slugs.add(slug)
                                if len(similar_products) >= 3:
                                    break
                except:
                    continue
            
            result["similar_products"] = similar_products[:3]
            if similar_products:
                print(f"[DEBUG]   Found {len(similar_products)} similar products: {similar_products}")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract similar_products: {e}")
        
        # 5. Extract Description
        try:
            import json
            import re
            desc = None
            # Try extracting from Apollo/Next.js data first (more reliable)
            html = page.html
            
            # Reuse regex from module level if possible, or define here
            apollo_re = re.compile(r'window\[Symbol\.for\("ApolloSSRDataTransport"\)\] \?\?= \[\]\)\.push\((.*?)\);', re.S)
            m_apollo = apollo_re.search(html)
            if m_apollo:
                print("[DEBUG]   Found Apollo SSR data pattern")
                try:
                    json_str = m_apollo.group(1)
                    json_str = json_str.replace("undefined", "null")
                    data, _ = json.JSONDecoder().raw_decode(json_str)
                    print("[DEBUG]   Successfully parsed Apollo JSON")
                    if "rehydrate" in data:
                        rehydrate = data["rehydrate"]
                        print(f"[DEBUG]   Iterating {len(rehydrate)} keys in rehydrate")
                        for key, val in rehydrate.items():
                            if not val or "data" not in val:
                                continue
                            data_inner = val["data"]
                            if not data_inner:
                                continue
                            
                            # Check for 'post'
                            if "post" in data_inner:
                                post = data_inner["post"]
                                # print(f"[DEBUG]     Found 'post' in {key}")
                                if post and post.get("description"):
                                    desc = post.get("description")
                                    print(f"[DEBUG]   Found description in Apollo post: {desc[:50]}...")
                                    break
                                    
                            # Check for 'product'
                            if "product" in data_inner:
                                prod = data_inner["product"]
                                # print(f"[DEBUG]     Found 'product' in {key}")
                                if prod and prod.get("description"):
                                    desc = prod.get("description")
                                    print(f"[DEBUG]   Found description in Apollo product: {desc[:50]}...")
                                    break
                except Exception as e:
                    print(f"[DEBUG]   Error parsing Apollo JSON: {e}")
            else:
                print("[DEBUG]   Apollo SSR data pattern NOT found")
                with open("debug_failed_apollo.html", "w") as f:
                    f.write(html)
                print("[DEBUG]   Saved HTML to debug_failed_apollo.html")
            
            # Fallback to meta tags
            if not desc:
                try:
                    desc_elem = page.ele('css:meta[name="description"]', timeout=1)
                    if desc_elem:
                        desc = desc_elem.attr("content")
                except:
                    pass
                
            if not desc:
                try:
                    desc_elem = page.ele('css:meta[property="og:description"]', timeout=1)
                    if desc_elem:
                        desc = desc_elem.attr("content")
                except:
                    pass
            
            if desc:
                result["description"] = desc
                # print(f"[DEBUG]   Found description: {desc[:50]}...")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract description: {e}")

        # 6. Extract Topics
        try:
            topics = []
            topic_links = page.eles('css:a[href^="/topics/"]')
            seen_topics = set()
            for link in topic_links:
                if link.states.is_displayed:
                    text = link.text.strip()
                    if text and text not in seen_topics:
                        topics.append(text)
                        seen_topics.add(text)
            
            if topics:
                result["topics"] = topics
                print(f"[DEBUG]   Found {len(topics)} topics: {topics}")
        except Exception as e:
            print(f"[DEBUG]   Failed to extract topics: {e}")

    except Exception as e:
        print(f"[ERROR] Failed to scrape {product_url} with drission: {e}")
    
    return result


def augment_with_product_pages(products: List[dict], session: Optional[requests.Session] = None, drission_page: Optional[ChromiumPage] = None) -> List[dict]:
    """
    Augment products with data scraped from product pages using DrissionPage.
    Fetches: Followers, Company_Info, team_members, Similar_Product
    """
    result: List[dict] = []
    print(f"[DEBUG] Starting to augment {len(products)} products with drission page scraping...")
    
    # Initialize drission page if not provided
    if drission_page is None:
        cfg = load_config()
        cookies_str = cfg.get("PH_COOKIES", "")
        
        co = ChromiumOptions()
        # co.headless()
        drission_page = ChromiumPage(addr_or_opts=co)
        
        # Set cookies if available
        # if cookies:
        #     drission_page.set.cookies(cookies)
        #     print(f"[DEBUG] Set {len(cookies)} cookies for drission")
    
    for idx, p in enumerate(products):
        product_url = p.get("url", "")
        if not product_url:
            print(f"[DEBUG] Processing {p.get('name', 'unknown')} ({idx+1}/{len(products)})...")
            print(f"[DEBUG]   No URL found")
            result.append(p)
            continue
        
        print(f"[DEBUG] Processing {p.get('name', 'unknown')} ({idx+1}/{len(products)}) from URL: {product_url}...")
        
        # Scrape with drission
        scraped_data = scrape_product_page_with_drission(product_url, drission_page)
        
        # Enrich product with scraped data
        enriched = dict(p)
        
        # Update followers
        if scraped_data.get("followers") and not enriched.get("followers"):
            enriched["followers"] = scraped_data["followers"]
        
        # Update company_info
        if scraped_data.get("company_info") and not enriched.get("company_info"):
            enriched["company_info"] = scraped_data["company_info"]
        
        # Update team_members (makers)
        if scraped_data.get("team_members") and not enriched.get("makers"):
            enriched["makers"] = scraped_data["team_members"]
        
        # Update similar_products
        if scraped_data.get("similar_products") and not enriched.get("similar_products"):
            enriched["similar_products"] = scraped_data["similar_products"]
            
        # Update description
        if scraped_data.get("description") and not enriched.get("description"):
            enriched["description"] = scraped_data["description"]
            
        # Update topics (Launch_tags)
        if scraped_data.get("topics") and not enriched.get("topics"):
            enriched["topics"] = scraped_data["topics"]
        
        result.append(enriched)
        
        # Be polite - wait between requests
        if idx < len(products) - 1:
            time.sleep(1)
    
    # Close drission page if we created it
    if drission_page:
        try:
            drission_page.quit()
        except:
            pass
    
    print(f"[DEBUG] Completed augmentation for {len(result)} products")
    return result


def map_to_bitable_fields(products: List[dict], tz_name: str, week_start_date: Optional[datetime] = None) -> List[dict]:
    now_str = now_cn_str(tz_name)
    week_str = ""
    ph_weekly_str = ""
    week_ts: Optional[int] = None
    if week_start_date is not None:
        # Use YYYY-MM-DD for Feishu date field
        local_dt = week_start_date.astimezone(pytz.timezone(tz_name))
        week_str = local_dt.strftime("%Y/%m/%d")
        iso_year, iso_week, _ = local_dt.isocalendar()
        ph_weekly_str = f"{iso_year}-W{int(iso_week):02d}"
        # Feishu date expects unix timestamp (ms)
        week_ts = int(local_dt.timestamp() * 1000)
    items: List[dict] = []
    for node in products:
        ph_url = node.get("url", "") or ""
        website = node.get("website", "") or ""
        link_ph = {"text": node.get("name") or ph_url, "link": ph_url} if ph_url else ""
        link_site = {"text": website, "link": website} if website else ""
        tagline_val = node.get("tagline", "")
        brief_val = tagline_val if tagline_val else ""
        # Get team_members from makers field (populated by drission scraping)
        makers_val = node.get("makers") or []
        if len(items) < 3:  # Debug first 3 products
            print(f"[DEBUG] Mapping Brief for {node.get('name')}: tagline='{tagline_val[:50] if tagline_val else '(empty)'}...', Brief='{brief_val[:50] if brief_val else '(empty)'}...'")
            if makers_val:
                print(f"[DEBUG] Mapping team_members for {node.get('name')}: {makers_val}")
        items.append(
            {
                "Product_Name": node.get("name", ""),
                "Upvote": int(node.get("votesCount") or 0),
                "Launch_tags": node.get("topics") or [],
                "Brief": brief_val,
                "Description": node.get("description", ""),
                "team_members": makers_val if isinstance(makers_val, list) else [],
                "Forum": {"text": "Discussion", "link": ph_url} if ph_url else "",
                "Social": link_site,
                "PH_Link": link_ph,
                "PH_Id": str(node.get("id", "")),
                "Last_Updated": now_str,
                "Week_Range": week_ts if week_ts is not None else week_str,
                "PH_Weekly": ph_weekly_str,
                "Followers": (node.get("followers") if isinstance(node.get("followers"), str) else str(node.get("followers")) if node.get("followers") is not None else ""),
                "Company_Info": ({"text": node.get("company_info"), "link": node.get("company_info")} if (node.get("company_info") and node.get("company_info").strip()) else None),
                "Similar_Product": (node.get("similar_products")[0] if isinstance(node.get("similar_products"), list) and len(node.get("similar_products")) > 0 else (node.get("similar_products") if isinstance(node.get("similar_products"), str) else "")),
            }
        )
    print(f"[DEBUG] Mapped {len(items)} products, {sum(1 for item in items if item.get('Brief'))} with Brief field")
    return items


# ---------- Feishu API ----------

def feishu_access_token(app_id: str, app_secret: str) -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None) and not data.get("tenant_access_token"):
        raise RuntimeError(f"Feishu auth failed: {data}")
    return data.get("tenant_access_token") or data.get("data", {}).get("tenant_access_token")


def feishu_list_all_records(token: str, app_token: str, table_id: str) -> List[dict]:
    records: List[dict] = []
    page_token = None
    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    no_proxy = {"http": None, "https": None}
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(base, headers=headers, params=params, timeout=30, proxies=no_proxy)
        r.raise_for_status()
        body = r.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Feishu list records error: {body}")
        page = body.get("data", {})
        records.extend(page.get("items", []))
        if not page.get("has_more"):
            break
        page_token = page.get("page_token")
    return records


def build_existing_index(records: List[dict]) -> Dict[str, str]:
    # Map PH_Id -> record_id
    idx: Dict[str, str] = {}
    for rec in records:
        fields = rec.get("fields", {})
        ph_id = fields.get("PH_Id")
        if isinstance(ph_id, list):  # Feishu text fields may appear as list
            ph_id = ph_id[0] if ph_id else ""
        if isinstance(ph_id, (int, float)):
            ph_id = str(ph_id)
        if isinstance(ph_id, str) and ph_id:
            idx[ph_id] = rec.get("record_id") or rec.get("id")
    return idx


def feishu_batch_create(token: str, app_token: str, table_id: str, records: List[dict]) -> None:
    if not records:
        return
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"records": [{"fields": r} for r in records]}
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    r = requests.post(url, headers=headers, json=body, timeout=60, proxies={"http": None, "https": None})
    r.raise_for_status()
    data = r.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Feishu batch_create error: {data}")


def feishu_batch_update(token: str, app_token: str, table_id: str, updates: List[Tuple[str, dict]]) -> None:
    if not updates:
        return
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"records": [{"record_id": rid, "fields": fields} for rid, fields in updates]}
    # Debug: log team_members field format for first update
    if updates:
        first_fields = updates[0][1]
        if "team_members" in first_fields:
            print(f"[DEBUG] team_members field format in update: {type(first_fields['team_members'])}, value: {first_fields['team_members']}")
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    r = requests.post(url, headers=headers, json=body, timeout=60, proxies={"http": None, "https": None})
    r.raise_for_status()
    data = r.json()
    if data.get("code", 0) != 0:
        print(f"[ERROR] Feishu batch_update error response: {json.dumps(data, indent=2)}")
        raise RuntimeError(f"Feishu batch_update error: {data}")


def feishu_notify_text(token: str, open_id: str, text: str) -> None:
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"receive_id": open_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    r = requests.post(url, headers=headers, json=body, timeout=30, proxies={"http": None, "https": None})
    r.raise_for_status()
    data = r.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Feishu notify error: {data}")


def feishu_list_field_names(token: str, app_token: str, table_id: str) -> List[str]:
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    names: List[str] = []
    page_token = None
    # Disable proxy for Feishu API (domestic API, doesn't need proxy)
    no_proxy = {"http": None, "https": None}
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(url, headers=headers, params=params, timeout=30, proxies=no_proxy)
        r.raise_for_status()
        body = r.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Feishu list fields error: {body}")
        data = body.get("data", {})
        for f in data.get("items", []):
            n = f.get("field_name") or f.get("name")
            if n:
                names.append(n)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return names


# ---------- ProductHunt GraphQL (preferred) ----------

GRAPHQL_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"


def week_start_end(year: int, iso_week: int, tz_name: str) -> Tuple[datetime, datetime]:
    tz = pytz.timezone(tz_name)
    # ISO week Monday
    # Find Jan 4th, which is always in week 1
    jan4 = datetime(year, 1, 4, tzinfo=tz)
    jan4_weekday = jan4.isoweekday()
    week1_monday = jan4 - timedelta(days=jan4_weekday - 1)
    start = week1_monday + timedelta(weeks=iso_week - 1)
    end = start + timedelta(days=7)
    return start, end


def parse_week_from_url(url: str) -> Optional[Tuple[int, int]]:
    # expect .../weekly/<year>/<week>
    m = re.search(r"/weekly/(\d{4})/(\d{1,2})", url)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def fetch_week_via_graphql(token: str, start: datetime, end: datetime) -> List[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    products: List[dict] = []
    after = None
    # Format times in ISO8601 with Z (PH expects UTC timestamps)
    start_iso = start.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = (
        "query($after: String, $start: DateTime!, $end: DateTime!) { "
        "posts(order: RANKING, featured: true, postedAfter: $start, postedBefore: $end, first: 50, after: $after) { "
        "edges { node { id name tagline description votesCount topics { edges { node { name } } } makers { name } website url commentsCount } cursor } "
        "pageInfo { hasNextPage endCursor } } }"
    )
    while True:
        body = {"query": query, "variables": {"after": after, "start": start_iso, "end": end_iso}}
        max_retries = 3
        retry_delay = 2
        r = None
        for attempt in range(max_retries):
            try:
                r = requests.post(GRAPHQL_ENDPOINT, headers=headers, json=body, timeout=30)
                r.raise_for_status()
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    print(f"[WARN] GraphQL request failed, retrying in {retry_delay}s... (attempt {attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
        data = r.json()
        edges = (((data or {}).get("data") or {}).get("posts") or {}).get("edges") or []
        for e in edges:
            node = e.get("node") or {}
            tagline_val = node.get("tagline")
            makers_raw = node.get("makers") or []
            makers_list = [m.get("name") for m in makers_raw if isinstance(m, dict) and m.get("name")]
            # Check if names are redacted
            if makers_list and all(name == "[REDACTED]" for name in makers_list):
                makers_list = []  # Clear redacted names, will try to get from scraping
                if len(products) < 3:
                    print(f"[WARN] GraphQL returned [REDACTED] for makers of {node.get('name')}, will try scraping")
            if len(products) < 3:  # Debug first 3 products
                if tagline_val:
                    print(f"[DEBUG] GraphQL extracted tagline for {node.get('name')}: {tagline_val[:60]}...")
                if makers_list:
                    print(f"[DEBUG] GraphQL extracted makers for {node.get('name')}: {makers_list}")
                elif makers_raw:
                    print(f"[DEBUG] GraphQL makers raw for {node.get('name')}: {makers_raw[:2]}... (could not extract names)")
            products.append(
                {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "tagline": tagline_val,
                    "description": node.get("description"),
                    "votesCount": node.get("votesCount"),
                    "commentsCount": node.get("commentsCount"),
                    "url": node.get("url"),
                    "website": node.get("website"),
                    "makers": makers_list,
                    "topics": [ed.get("node", {}).get("name") for ed in ((node.get("topics") or {}).get("edges") or []) if ed.get("node", {}).get("name")],
                }
            )
        page_info = (((data or {}).get("data") or {}).get("posts") or {}).get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
    print(f"[DEBUG] GraphQL fetched {len(products)} products, {sum(1 for p in products if p.get('tagline'))} with tagline, {sum(1 for p in products if p.get('makers'))} with makers")
    return products


# ---------- Sync job ----------

def run_sync() -> None:
    cfg = load_config()
    tz = cfg["TIMEZONE"]
    url_env = (cfg.get("PH_WEEKLY_URL") or "").strip().lower()
    try:
        week_offset = int(cfg.get("PH_WEEK_OFFSET", "0"))
    except Exception:
        week_offset = 0
    if not url_env or url_env == "auto":
        weekly_url = compute_weekly_url(tz, week_offset=week_offset)
    else:
        weekly_url = (cfg.get("PH_WEEKLY_URL") or "").strip()

    if not (cfg["FEISHU_APP_ID"] and cfg["FEISHU_APP_SECRET"] and cfg["FEISHU_TABLE_APP_ID"] and cfg["FEISHU_TABLE_ID"] and cfg["FEISHU_RECEIVER_OPEN_ID"]):
        print("[ERROR] Missing Feishu configuration. Please set environment variables.")
        sys.exit(1)

    print(f"[INFO] Start sync at {now_cn_str(tz)} for weekly: {weekly_url}")

    # Initialize session with cookies and proxy if provided (early, for use in fetch_weekly_page)
    global _ph_session
    ph_cookies = cfg.get("PH_COOKIES", "").strip()
    proxy_config = {
        "PROXY_HTTP": cfg.get("PROXY_HTTP"),
        "PROXY_HTTPS": cfg.get("PROXY_HTTPS"),
        "PROXY_ALL": cfg.get("PROXY_ALL"),
    }
    # Only use proxy if it's actually set (not None)
    has_proxy = any(v for v in proxy_config.values() if v is not None)
    if ph_cookies or has_proxy:
        _ph_session = create_ph_session(ph_cookies, proxy_config=proxy_config if has_proxy else None)
        print(f"[DEBUG] Initialized session with cookies{' and proxy' if has_proxy else ''}")
    else:
        _ph_session = None
        print(f"[DEBUG] No cookies/proxy provided, using default requests")

    # 1) Fetch PH weekly (prefer GraphQL when token provided)
    ph_token = (cfg.get("PH_BEARER_TOKEN") or "").strip()
    products: List[dict]
    week_start_for_field: Optional[datetime] = None
    if ph_token:
        print(f"[DEBUG] Using GraphQL API with token (length: {len(ph_token)})")
        parsed = parse_week_from_url(weekly_url)
        if parsed is None:
            # fallback to current computed week if URL wasn't parsable
            now_local = datetime.now(pytz.timezone(tz))
            parsed = (now_local.isocalendar().year, now_local.isocalendar().week)
        year, week_no = parsed
        start_dt, end_dt = week_start_end(year, int(week_no), tz)
        week_start_for_field = start_dt
        products = fetch_week_via_graphql(ph_token, start_dt, end_dt)
    else:
        # fallback to page scrape (may 403)
        print(f"[DEBUG] No PH_BEARER_TOKEN found, falling back to page scraping")
        next_data = fetch_weekly_page(weekly_url, session=_ph_session)
        products = parse_weekly_products(next_data)
        parsed = parse_week_from_url(weekly_url)
        if parsed is not None:
            year, week_no = parsed
            start_dt, _ = week_start_end(year, int(week_no), tz)
            week_start_for_field = start_dt
    # Attempt to fill gaps from the weekly page if any Brief/makers/website/topics missing
    needs_augment = any((not p.get("tagline") or not p.get("website") or not p.get("makers") or not p.get("topics")) for p in products)
    if needs_augment:
        products = augment_from_weekly_page(weekly_url, products, session=_ph_session)
    
    # Initialize Playwright browser with proxy if available (from config or env)
    # TEMPORARILY DISABLED: Skip Playwright and product page scraping to speed up
    # if PLAYWRIGHT_AVAILABLE:
    #     # Check if proxy is set in config or environment (only if not None)
    #     has_proxy = any(v for v in proxy_config.values() if v is not None) or os.getenv("http_proxy") or os.getenv("HTTP_PROXY") or os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")
    #     if has_proxy:
    #         init_playwright_browser(proxy_config=proxy_config if any(v for v in proxy_config.values() if v is not None) else None)
    #     else:
    # try product pages for followers & company info (best-effort) using drission
    print(f"[DEBUG] Starting product page scraping with drission...")
    products = augment_with_product_pages(products, session=_ph_session)
    mapped = map_to_bitable_fields(products, tz, week_start_date=week_start_for_field)

    # 2) Feishu auth
    token = feishu_access_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    # discover available field names and filter mapped payloads to avoid FieldNameNotFound
    available_fields = set(feishu_list_field_names(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"]))
    print(f"[DEBUG] Available Feishu fields: {sorted(available_fields)}")
    if "Brief" not in available_fields:
        print(f"[WARN] 'Brief' field not found in Feishu table! Available fields containing 'brief': {[f for f in available_fields if 'brief' in f.lower()]}")

    # 3) Load existing records and de-duplicate (only within the same week)
    existing_records = feishu_list_all_records(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"])
    # compute current week keys
    cur_week_str = ""
    cur_ph_weekly = ""
    if week_start_for_field is not None:
        local_dt = week_start_for_field.astimezone(pytz.timezone(tz))
        cur_week_str = local_dt.strftime("%Y/%m/%d")
        iso_year, iso_week, _ = local_dt.isocalendar()
        cur_ph_weekly = f"{iso_year}-W{int(iso_week):02d}"

    def normalize_field_str(fields: dict, name: str) -> str:
        v = fields.get(name)
        if isinstance(v, list):
            v = v[0] if v else ""
        if isinstance(v, dict):
            # link or text objects
            return v.get("text") or v.get("link") or ""
        if v is None:
            return ""
        return str(v)

    filtered_records = []
    if "PH_Weekly" in available_fields and cur_ph_weekly:
        for rec in existing_records:
            if normalize_field_str(rec.get("fields", {}), "PH_Weekly") == cur_ph_weekly:
                filtered_records.append(rec)
    elif "Week_Range" in available_fields and cur_week_str:
        for rec in existing_records:
            if normalize_field_str(rec.get("fields", {}), "Week_Range") == cur_week_str:
                filtered_records.append(rec)
    else:
        # if no week fields exist, fall back to all (can't scope)
        filtered_records = existing_records

    idx = build_existing_index(filtered_records)

    creates: List[dict] = []
    updates: List[Tuple[str, dict]] = []

    for item in mapped:
        # filter out fields that do not exist in the table to prevent errors, and remove None values
        # Note: Keep empty strings for Brief field (they may be valid updates)
        original_brief = item.get("Brief")
        original_team_members = item.get("team_members")
        item = {k: v for k, v in item.items() if k in available_fields and v is not None}
        # Always include Brief field if it exists in available_fields, even if empty string
        if "Brief" in available_fields and original_brief is not None:
            item["Brief"] = original_brief
        # Always include team_members field if it exists in available_fields, even if empty list
        if "team_members" in available_fields and original_team_members is not None:
            # Keep empty list as [] (not None)
            item["team_members"] = original_team_members if original_team_members else []
        # Debug: check if Brief/team_members were filtered out
        if len(updates) < 3 or len(creates) < 3:  # Debug first 3 items
            filtered_brief = item.get("Brief")
            filtered_team_members = item.get("team_members")
            if original_brief and not filtered_brief:
                print(f"[WARN] Brief field filtered out for {item.get('Product_Name')}: original='{original_brief[:50]}...', in available_fields={('Brief' in available_fields)}, is None={original_brief is None}")
            elif filtered_brief:
                print(f"[DEBUG] Brief kept for {item.get('Product_Name')}: '{filtered_brief[:50]}...'")
            if original_team_members and not filtered_team_members:
                print(f"[WARN] team_members field filtered out for {item.get('Product_Name')}: original={original_team_members}, in available_fields={('team_members' in available_fields)}, is None={original_team_members is None}")
            elif filtered_team_members:
                print(f"[DEBUG] team_members kept for {item.get('Product_Name')}: {filtered_team_members}")
        ph_id = str(item.get("PH_Id", ""))
        if not ph_id:
            continue
        rec_id = idx.get(ph_id)
        if rec_id:
            updates.append((rec_id, item))
        else:
            creates.append(item)

    # 4) Push changes
    print(f"[INFO] Preparing to sync: {len(creates)} new records, {len(updates)} updates")
    if creates:
        print(f"[INFO] Creating {len(creates)} new records...")
        feishu_batch_create(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], creates)
        print(f"[INFO] Successfully created {len(creates)} records")
    if updates:
        print(f"[INFO] Updating {len(updates)} existing records...")
        feishu_batch_update(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], updates)
        print(f"[INFO] Successfully updated {len(updates)} records")

    # 5) Notify only if there are changes
    if creates or updates:
        text = f"ProductHunt 每周榜单同步完成\n新增 {len(creates)} 条，更新 {len(updates)} 条。\n时间：{now_cn_str(tz)}"
        feishu_notify_text(token, cfg["FEISHU_RECEIVER_OPEN_ID"], text)
        print(f"[INFO] Notification sent. Created: {len(creates)}, Updated: {len(updates)}")
    else:
        print(f"[INFO] Sync finished. No changes (Created: {len(creates)}, Updated: {len(updates)})")
    
    # Optional: Trigger team member scraper async (if enabled)
    if cfg.get("ENABLE_TEAM_SCRAPER"):
        def run_team_scraper():
            script_path = os.path.join(os.path.dirname(__file__), "scrape_team_drission.py")
            if os.path.exists(script_path):
                print("[INFO] Starting team member scraper in background...")
                try:
                    # Run scraper as subprocess
                    subprocess.Popen(
                        [sys.executable, script_path],
                        cwd=os.path.dirname(__file__),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    print("[INFO] Team member scraper started")
                except Exception as e:
                    print(f"[ERROR] Failed to start team member scraper: {e}")
            else:
                print(f"[WARN] Team scraper script not found: {script_path}")
        
        # Run in thread to not block main workflow
        thread = threading.Thread(target=run_team_scraper, daemon=True)
        thread.start()
    
    # Note: Playwright browser is kept open for reuse in next sync (closed on program exit)


def main():
    parser = argparse.ArgumentParser(description="ProductHunt → Feishu weekly sync")
    parser.add_argument("--once", action="store_true", help="Run once immediately and exit")
    args = parser.parse_args()

    # Register cleanup function to close Playwright browser on exit
    atexit.register(close_playwright_browser)

    if args.once:
        try:
            run_sync()
        finally:
            close_playwright_browser()
        return

    cfg = load_config()
    tz_name = cfg.get("TIMEZONE", "Asia/Shanghai")
    timezone = pytz.timezone(tz_name)

    sched = BlockingScheduler(timezone=timezone)
    # Every day at 08:00 local time
    sched.add_job(run_sync, CronTrigger(hour=8, minute=0, timezone=timezone), id="daily_sync", replace_existing=True)
    print(f"[INFO] Scheduler started. Daily at 08:00 {tz_name}.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("[INFO] Scheduler stopped.")
    finally:
        close_playwright_browser()


if __name__ == "__main__":
    main()


