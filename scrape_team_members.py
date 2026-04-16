#!/usr/bin/env python3
"""
ProductHunt Team Member Scraper

Standalone script to scrape team member information from ProductHunt product pages.
Uses Playwright to click the "Team" button and extract team member names.

Configuration via environment variables (reads from .env file):
  FEISHU_APP_ID                Feishu App ID
  FEISHU_APP_SECRET            Feishu App Secret
  FEISHU_TABLE_APP_ID          Feishu Bitable App Token
  FEISHU_TABLE_ID              Feishu Bitable Table ID
  PH_COOKIES                   Optional ProductHunt cookies
  PROXY settings               Optional proxy configuration

Usage:
  python scrape_team_members.py                    # Process all records with empty team_members
  python scrape_team_members.py --limit 10         # Process only 10 records
  python scrape_team_members.py --url <URL>        # Process single URL (for testing)
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    print("[ERROR] Playwright not available. Install with: pip install playwright && playwright install chromium")
    sys.exit(1)

import requests


# ---------- Configuration ----------

def load_config() -> Dict[str, str]:
    if load_dotenv is not None:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    
    proxy_http = os.getenv("http_proxy") or os.getenv("HTTP_PROXY") or None
    proxy_https = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or None
    
    return {
        "PH_COOKIES": os.getenv("PH_COOKIES", ""),
        "PROXY_HTTP": proxy_http,
        "PROXY_HTTPS": proxy_https,
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET", ""),
        "FEISHU_TABLE_APP_ID": os.getenv("FEISHU_TABLE_APP_ID", ""),
        "FEISHU_TABLE_ID": os.getenv("FEISHU_TABLE_ID", ""),
    }


# ---------- Feishu API ----------

def feishu_access_token(app_id: str, app_secret: str) -> str:
    """Get Feishu access token."""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, 
                        timeout=30, proxies={"http": None, "https": None})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None) and not data.get("tenant_access_token"):
        raise RuntimeError(f"Feishu auth failed: {data}")
    return data.get("tenant_access_token") or data.get("data", {}).get("tenant_access_token")


def feishu_list_all_records(token: str, app_token: str, table_id: str) -> List[dict]:
    """List all records from Feishu Bitable."""
    records: List[dict] = []
    page_token = None
    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
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


def feishu_batch_update(token: str, app_token: str, table_id: str, updates: List[tuple]) -> None:
    """Batch update records in Feishu Bitable."""
    if not updates:
        return
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"records": [{"record_id": rid, "fields": fields} for rid, fields in updates]}
    
    r = requests.post(url, headers=headers, json=body, timeout=60, proxies={"http": None, "https": None})
    r.raise_for_status()
    data = r.json()
    if data.get("code", 0) != 0:
        print(f"[ERROR] Feishu batch_update error response: {json.dumps(data, indent=2)}")
        raise RuntimeError(f"Feishu batch_update error: {data}")


# ---------- ProductHunt Scraper ----------

def parse_cookies_from_string(cookie_str: str) -> List[dict]:
    """Parse cookie string like 'key1=value1; key2=value2' into Playwright cookie format."""
    if not cookie_str:
        return []
    
    cookies = []
    for cookie in cookie_str.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".producthunt.com",
                "path": "/",
            })
    return cookies


def extract_slug_from_url(url: str) -> Optional[str]:
    """Extract product slug from ProductHunt URL."""
    if not url:
        return None
    # Support both /products/<slug> and /posts/<slug>
    m = re.search(r"/(?:products|posts)/([\w-]+)", url)
    return m.group(1) if m else None


def scrape_team_members(product_url: str, cookies: Optional[List[dict]] = None, proxy_config: Optional[Dict[str, str]] = None, debug: bool = False, headless: bool = True) -> List[str]:
    """
    Scrape team member names from ProductHunt product page.
    
    Steps:
    1. Navigate to product page
    2. Click "Team" button (span with text "Team")
    3. Extract team member names from links (a.text-16.font-semibold.text-dark-gray)
    
    Args:
        product_url: ProductHunt product URL
        cookies: Optional list of cookie dicts to bypass Cloudflare
        proxy_config: Optional proxy configuration
        debug: Enable debug mode with screenshots
        headless: Run browser in headless mode (False = visible browser)
    
    Returns list of team member names.
    """
    slug = extract_slug_from_url(product_url)
    if not slug:
        print(f"[ERROR] Could not extract slug from URL: {product_url}")
        return []
    
    print(f"[INFO] Scraping team members for: {slug}")
    
    with sync_playwright() as p:
        # Configure browser launch options - more realistic settings
        launch_options = {
            "headless": headless,
            "args": [
                '--disable-blink-features=AutomationControlled',  # Hide automation
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--window-size=1920,1080',
            ]
        }
        
        # If headless, use new headless mode which is harder to detect
        if headless:
            launch_options["args"].append('--headless=new')
        
        context_options = {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "has_touch": False,
            "is_mobile": False,
            "device_scale_factor": 1,
            # Add extra HTTP headers to look more like real browser
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
                "Upgrade-Insecure-Requests": "1",
            }
        }
        
        # Add proxy if configured
        if proxy_config:
            proxy_http = proxy_config.get("PROXY_HTTP") or proxy_config.get("PROXY_HTTPS")
            if proxy_http:
                if not proxy_http.startswith(("http://", "https://", "socks5://")):
                    proxy_http = f"http://{proxy_http}"
                proxy_server = proxy_http
                launch_options["proxy"] = {"server": proxy_server}
                context_options["proxy"] = {"server": proxy_server}
                print(f"[DEBUG] Using proxy: {proxy_server}")
        
        try:
            browser = p.chromium.launch(**launch_options)
            context = browser.new_context(**context_options)
            
            # Add cookies if provided (to bypass Cloudflare)
            if cookies:
                context.add_cookies(cookies)
                print(f"[DEBUG] Added {len(cookies)} cookies to context")
            
            page = context.new_page()
            
            # Add JavaScript to hide webdriver property and other automation signals
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                // Override the plugins to avoid headless detection
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                
                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                
                // Chrome specific properties
                window.chrome = {
                    runtime: {}
                };
                
                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            
            # Set shorter timeout for faster failures
            page.set_default_timeout(20000)  # 20 seconds
            
            # Try both /products/ and /posts/ paths
            team_members = []
            for path in ["products", "posts"]:
                url = f"https://www.producthunt.com/{path}/{slug}"
                try:
                    print(f"[DEBUG] Navigating to: {url}")
                    # Use 'domcontentloaded' instead of 'networkidle' for faster loading
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    
                    # Wait longer for dynamic content - SLOWED DOWN
                    print(f"[DEBUG] Waiting for page to fully load...")
                    time.sleep(5)  # 5 seconds
                    
                    # Take screenshot for debugging (optional)
                    if debug:
                        screenshot_path = f"/tmp/ph_debug_{slug}.png"
                        page.screenshot(path=screenshot_path)
                        print(f"[DEBUG] Screenshot saved to: {screenshot_path}")
                    
                    # Scroll down to load team section - SLOWED DOWN
                    print(f"[DEBUG] Scrolling to load content...")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    time.sleep(3)  # Wait 3 seconds after scroll
                    
                    # Look for Team button/tab
                    # Multiple possible selectors for the Team button
                    team_button_selectors = [
                        'button:has-text("Team")',
                        'span.text-sm.font-semibold:has-text("Team")',
                        'a:has-text("Team")',
                        '[role="tab"]:has-text("Team")',
                        'div:has-text("Team")',
                    ]
                    
                    team_button_clicked = False
                    for selector in team_button_selectors:
                        try:
                            button = page.locator(selector).first
                            if button.is_visible(timeout=3000):
                                print(f"[DEBUG] Found Team button with selector: {selector}")
                                button.click()
                                print(f"[INFO] Clicked Team button, waiting for team content to load...")
                                
                                # Wait long enough for content to load (no verification check)
                                # Cookies should bypass Cloudflare
                                page.wait_for_timeout(10000)  # 10 seconds - give it time
                                
                                print(f"[DEBUG] Team content should be loaded, proceeding to extract members...")
                                
                                team_button_clicked = True
                                break
                        except Exception as e:
                            print(f"[DEBUG] Team button selector {selector} failed: {e}")
                            continue
                    
                    if not team_button_clicked:
                        print(f"[DEBUG] Team button not found or not clickable, checking if team section is visible anyway")
                    
                    # Extract team member names
                    # Look for links to user profiles (/@username)
                    
                    # Try multiple selectors to find team member links
                    member_selectors = [
                        'a[href^="/@"].text-16.font-semibold',  # Most specific
                        'a[href^="/@"].font-semibold',
                    ]
                    
                    seen_hrefs = set()  # Track hrefs to avoid duplicates from same person
                    for selector in member_selectors:
                        try:
                            links = page.locator(selector).all()
                            print(f"[DEBUG] Checking {len(links)} links with selector: {selector}")
                            
                            for link in links:
                                try:
                                    name = link.inner_text(timeout=1000).strip()
                                    href = link.get_attribute("href") or ""
                                    
                                    # Only process each user once (by href)
                                    if href.startswith("/@") and href not in seen_hrefs and name:
                                        team_members.append(name)
                                        seen_hrefs.add(href)
                                        print(f"[DEBUG] Found team member: {name} ({href})")
                                except Exception:
                                    continue
                        except Exception as e:
                            print(f"[DEBUG] Selector {selector} failed: {e}")
                            continue
                    
                    if team_members:
                        print(f"[INFO] Successfully extracted {len(team_members)} team members from {path}/{slug}")
                        break  # Success, no need to try other path
                    else:
                        print(f"[WARN] No team members found on {path}/{slug}")
                        if path == "products":
                            continue  # Try /posts/ path
                
                except PlaywrightTimeoutError as e:
                    print(f"[WARN] Timeout accessing {path}/{slug}: {e}")
                    if path == "products":
                        continue  # Try /posts/ path
                except Exception as e:
                    print(f"[ERROR] Error scraping {path}/{slug}: {e}")
                    if path == "products":
                        continue
            
            browser.close()
            return team_members
            
        except Exception as e:
            print(f"[ERROR] Failed to scrape {product_url}: {e}")
            return []



# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Scrape ProductHunt team members")
    parser.add_argument("--url", help="Single product URL to scrape (for testing)")
    parser.add_argument("--limit", type=int, help="Limit number of records to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't update Feishu, just print results")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with screenshots")
    parser.add_argument("--headful", action="store_true", help="Run browser in visible mode (not headless)")
    parser.add_argument("--output-json", type=str, help="Save results to JSON file instead of updating Feishu")
    args = parser.parse_args()
    
    cfg = load_config()
    
    # Parse cookies if provided
    cookies = parse_cookies_from_string(cfg.get("PH_COOKIES", ""))
    if cookies:
        print(f"[INFO] Using {len(cookies)} cookies for authentication")
    
    # Single URL mode (for testing)
    if args.url:
        print(f"[INFO] Testing single URL: {args.url}")
        proxy_config = {
            "PROXY_HTTP": cfg.get("PROXY_HTTP"),
            "PROXY_HTTPS": cfg.get("PROXY_HTTPS"),
        }
        team_members = scrape_team_members(
            args.url, 
            cookies=cookies,
            proxy_config=proxy_config if any(proxy_config.values()) else None,
            debug=args.debug,
            headless=not args.headful
        )
        print(f"[RESULT] Team members: {team_members}")
        return
    
    # Batch mode: read from Feishu
    if not (cfg["FEISHU_APP_ID"] and cfg["FEISHU_APP_SECRET"] and cfg["FEISHU_TABLE_APP_ID"] and cfg["FEISHU_TABLE_ID"]):
        print("[ERROR] Missing Feishu configuration. Set FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_TABLE_APP_ID, FEISHU_TABLE_ID")
        sys.exit(1)
    
    print("[INFO] Fetching records from Feishu Bitable...")
    token = feishu_access_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    records = feishu_list_all_records(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"])
    
    # Filter records with empty team_members
    to_process = []
    for rec in records:
        fields = rec.get("fields", {})
        team_members = fields.get("team_members")
        ph_link = fields.get("PH_Link")
        
        # Check if team_members is empty (None, [], or empty string)
        is_empty = not team_members or (isinstance(team_members, list) and len(team_members) == 0)
        
        if is_empty and ph_link:
            # Extract URL from link field
            url = None
            if isinstance(ph_link, dict):
                url = ph_link.get("link") or ph_link.get("text")
            elif isinstance(ph_link, str):
                url = ph_link
            
            if url:
                to_process.append({
                    "record_id": rec.get("record_id") or rec.get("id"),
                    "product_name": fields.get("Product_Name", "Unknown"),
                    "url": url,
                })
    
    print(f"[INFO] Found {len(to_process)} records with empty team_members")
    
    if args.limit:
        to_process = to_process[:args.limit]
        print(f"[INFO] Limited to {len(to_process)} records")
    
    if not to_process:
        print("[INFO] No records to process")
        return
    
    # Process each record
    proxy_config = {
        "PROXY_HTTP": cfg.get("PROXY_HTTP"),
        "PROXY_HTTPS": cfg.get("PROXY_HTTPS"),
    }
    has_proxy = any(v for v in proxy_config.values() if v)
    
    updates = []
    for idx, item in enumerate(to_process):
        print(f"\n[{idx+1}/{len(to_process)}] Processing: {item['product_name']}")
        team_members = scrape_team_members(
            item["url"],
            cookies=cookies,
            proxy_config=proxy_config if has_proxy else None,
            debug=args.debug if hasattr(args, 'debug') else False,
            headless=not args.headful if hasattr(args, 'headful') else True
        )
        
        if team_members:
            updates.append((item["record_id"], {"team_members": team_members}))
            print(f"[SUCCESS] Found {len(team_members)} team members: {team_members}")
        else:
            print(f"[WARN] No team members found for {item['product_name']}")
        
        # Be polite, add delay between requests
        if idx < len(to_process) - 1:
            time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"Scraping completed!")
    print(f"Processed: {len(to_process)} products")
    print(f"Found team members: {len(updates)} products")
    print(f"{'='*50}\n")
    
    # Save to JSON file if requested
    if args.output_json:
        import json
        output_data = []
        for record_id, fields in updates:
            # Find the original item
            item = next((i for i in to_process if i["record_id"] == record_id), None)
            if item:
                output_data.append({
                    "record_id": record_id,
                    "product_name": item["product_name"],
                    "url": item["url"],
                    "team_members": fields["team_members"]
                })
        
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"[SUCCESS] Saved {len(output_data)} results to: {args.output_json}")
        print(f"\nTo update Feishu later, run:")
        print(f"  python scrape_team_members.py --import-json {args.output_json}")
        return
    
    # Update Feishu (original behavior)
    if args.dry_run:
        print("[DRY-RUN] Skipping Feishu update")
        for record_id, fields in updates:
            print(f"  Would update record {record_id}: {fields}")
        return
    
    if updates:
            print(f"\n[INFO] Updating {len(updates)} records in Feishu...")
            feishu_batch_update(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], updates)
            print(f"[SUCCESS] Updated {len(updates)} records")
    else:
        print("\n[INFO] No updates to make")


if __name__ == "__main__":
    main()
