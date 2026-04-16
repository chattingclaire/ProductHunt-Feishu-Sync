#!/usr/bin/env python3
"""
ProductHunt Team Member Scraper using DrissionPage
Optimized for bypassing Cloudflare and handling dynamic content
"""
import argparse
import json
import os
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
from DrissionPage import ChromiumPage, ChromiumOptions
import requests
import pytz


# ---------- Configuration ----------

def load_config():
    load_dotenv()
    return {
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET", ""),
       "FEISHU_TABLE_APP_ID": os.getenv("FEISHU_TABLE_APP_ID", ""),
        "FEISHU_TABLE_ID": os.getenv("FEISHU_TABLE_ID", ""),
        "PH_COOKIES": os.getenv("PH_COOKIES", ""),
    }


# ---------- Feishu API ----------

def get_feishu_token(app_id: str, app_secret: str) -> Optional[str]:
    """Get Feishu access token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("tenant_access_token")
    except Exception as e:
        print(f"[ERROR] Failed to get Feishu token: {e}")
    return None


def fetch_feishu_records(token: str, app_id: str, table_id: str, latest_week_only: bool = False, timezone: str = "Asia/Shanghai") -> List[Dict]:
    """Fetch records from Feishu Bitable
    
    Args:
        token: Feishu access token
        app_id: Feishu app ID
        table_id: Feishu table ID
        latest_week_only: If True, only fetch records from the latest week
        timezone: Timezone for week calculation
    """
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_id}/tables/{table_id}/records/search"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Calculate target week if needed
    target_week_str = ""
    if latest_week_only:
        tz = pytz.timezone(timezone)
        today = datetime.now(tz).date()
        iso_weekday = today.isoweekday()
        monday = today if iso_weekday == 1 else (today - timedelta(days=iso_weekday - 1))
        target_week_str = monday.strftime("%Y/%m/%d")
        print(f"[INFO] Filtering for latest week: {target_week_str}")
    
    all_items = []
    page_token = None
    
    while True:
        payload = {"page_size": 500}
        if page_token:
            payload["page_token"] = page_token
        
        try:
            # Increase timeout and add retry logic
            max_retries = 3
            resp = None
            for attempt in range(max_retries):
                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=60)
                    break
                except requests.exceptions.Timeout:
                    if attempt < max_retries - 1:
                        print(f"[WARN] Request timeout, retrying ({attempt + 1}/{max_retries})...")
                        time.sleep(2)
                    else:
                        print(f"[WARN] Request timeout after {max_retries} attempts, using partial data")
                        # Continue with partial data if we got some records
                        if len(all_items) > 0:
                            break
                        raise
            
            if resp is None:
                # If we have some records, continue with them
                if len(all_items) > 0:
                    print(f"[WARN] Stopping due to API error, but have {len(all_items)} records so far")
                    break
                print(f"[ERROR] Failed to get response after {max_retries} attempts")
                break
                
            data = resp.json()
            
            if data.get("code") != 0:
                print(f"[ERROR] Feishu API error: {data}")
                # If we have some records, continue with them
                if len(all_items) > 0:
                    break
                break
            
            items = data.get("data", {}).get("items", [])
            for item in items:
                fields = item.get("fields", {})
                
                # Filter by week if latest_week_only is True
                if latest_week_only:
                    week_range = fields.get("Week_Range", "")
                    week_str = ""
                    if isinstance(week_range, (int, float)):
                        # It's a timestamp (in milliseconds), convert to date string
                        try:
                            dt = datetime.fromtimestamp(week_range / 1000)
                            week_str = dt.strftime("%Y/%m/%d")
                        except:
                            pass
                    elif isinstance(week_range, str):
                        week_str = week_range
                    
                    # Check if this record belongs to target week
                    # Week_Range might be "YYYY/MM/DD" or contain it
                    if week_str and target_week_str:
                        # Check if target week date is in the week_str (could be range or single date)
                        if target_week_str not in week_str and not week_str.startswith(target_week_str):
                            continue  # Skip records not from target week
                    elif not week_str:
                        # If no week_str found, skip this record when filtering by week
                        continue
                
                # Extract URL from PH_Link field (which is a dict or string)
                ph_link = fields.get("PH_Link", "")
                product_url = ""
                if isinstance(ph_link, dict):
                    product_url = ph_link.get("link", "")
                elif isinstance(ph_link, str):
                    product_url = ph_link
                
                if not product_url:
                    continue  # Skip records without URL
                
                # Extract Product Name (text field)
                p_name_raw = fields.get("Product_Name", "")
                product_name = ""
                if isinstance(p_name_raw, list) and len(p_name_raw) > 0:
                    product_name = p_name_raw[0].get("text", "")
                elif isinstance(p_name_raw, str):
                    product_name = p_name_raw
                
                all_items.append({
                    "record_id": item.get("record_id"),
                    "product_name": product_name,
                    "url": product_url,
                })
            
            page_token = data.get("data", {}).get("page_token")
            if not page_token:
                break
        except Exception as e:
            print(f"[ERROR] Failed to fetch records: {e}")
            # If we have some records, continue with them
            if len(all_items) > 0:
                print(f"[WARN] Continuing with {len(all_items)} records despite error")
                break
            break
    
    return all_items


def batch_update_feishu(token: str, app_id: str, table_id: str, updates: List[tuple]):
    """Batch update Feishu Bitable records"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_id}/tables/{table_id}/records/batch_update"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Process in batches of 500
    batch_size = 500
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        records = [{"record_id": rid, "fields": fields} for rid, fields in batch]
        
        payload = {"records": records}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            if data.get("code") != 0:
                print(f"[ERROR] Batch update failed: {data}")
            else:
                print(f"[INFO] Updated {len(batch)} records")
        except Exception as e:
            print(f"[ERROR] Batch update error: {e}")


# ---------- DrissionPage Scraper ----------

def parse_cookies(cookie_str: str) -> List[Dict]:
    """Parse cookie string to list of cookie dicts"""
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
            })
    return cookies


def scrape_team_members_drission(product_url: str, page: ChromiumPage) -> List[str]:
    """
    Scrape team members using DrissionPage
    
    Args:
        product_url: ProductHunt product URL
        page: DrissionPage ChromiumPage instance (reused across calls)
    
    Returns:
        List of team member names
    """
    if not product_url:
        return []
    
    print(f"[INFO] Scraping: {product_url}")
    
    try:
        team_clicked = False
        
        # Check if we are already on a makers page
        if '/makers' in product_url:
            print(f"[INFO] URL appears to be a makers page already, skipping navigation search.")
            page.get(product_url, timeout=20)
            page.wait(3)
            team_clicked = True
        else:
            # Navigate to product page
            page.get(product_url, timeout=30)
            # Wait for Cloudflare challenge to complete
            max_wait = 60  # Increase to 60 seconds
            waited = 0
            while waited < max_wait:
                page.wait(3)
                waited += 3
                title = page.title
                html = page.html[:500] if page.html else ""
                # Check if challenge is still active
                if title and "请稍候" not in title and "Just a moment" not in title and "challenge" not in html.lower():
                    print(f"[DEBUG] Cloudflare challenge passed after {waited}s")
                    break
                if waited % 6 == 0:  # Print every 6 seconds
                    print(f"[DEBUG] Waiting for Cloudflare challenge... ({waited}s)")
            
            page.wait(3)  # Additional wait for page load
            
            # Extract Company Info (Website URL) - BEFORE navigating to makers
            company_info = ""
            try:
                # Look for "Company Info" header and then the link
                # Based on user screenshot: Header "Company Info", then a link with website
                # We can try to find the text "Company Info" and look for nearby links
                
                # Strategy 1: Find "Company Info" text and get next link
                company_header = page.ele('text:Company Info')
                if company_header:
                    # The link is usually in a sibling div or parent's sibling
                    # Let's try to find a link with http/https in the vicinity
                    # Or use the specific class from user screenshot if possible, but classes change
                    # User provided: class="flex flex-row items-center gap-2 stroke-gray-900 text-sm text-gray-900"
                    
                    # Try to find the link container by class substring
                    website_link = page.ele('css:a[class*="stroke-gray-900"][target="_blank"]')
                    if website_link and website_link.states.is_displayed:
                        company_info = website_link.attr('href')
                        print(f"[DEBUG] Found Company Info URL: {company_info}")
            except Exception as e:
                print(f"[DEBUG] Failed to extract company info: {e}")
            
            # Strategy: Find the "Team" link which usually points to /makers
            # It might be visible directly, or inside "More" dropdown
            
            makers_url = None
            
            # 1. Check for visible /makers link directly
            try:
                makers_link = page.ele('css:a[href$="/makers"]')
                if makers_link and makers_link.states.is_displayed:
                    makers_url = makers_link.attr('href')
                    print(f"[DEBUG] Found direct makers link: {makers_url}")
            except:
                pass
                
            # 2. If not found, check "More" menu
            if not makers_url:
                print(f"[DEBUG] Direct makers link not found, checking 'More' menu...")
                try:
                    more_btns = page.eles('text:More')
                    for btn in more_btns:
                        if btn.states.is_displayed and btn.tag in ['span', 'div', 'button']:
                            btn.click()
                            page.wait(1)
                            
                            # Check for makers link in dropdown
                            try:
                                makers_link = page.ele('css:a[href$="/makers"]')
                                if makers_link and makers_link.states.is_displayed:
                                    makers_url = makers_link.attr('href')
                                    print(f"[DEBUG] Found makers link in dropdown: {makers_url}")
                                    break
                            except:
                                pass
                except Exception as e:
                    print(f"[DEBUG] Error checking More menu: {e}")
            
            # 3. Navigate to makers URL if found, or try constructing it directly
            if makers_url:
                if not makers_url.startswith('http'):
                    makers_url = 'https://www.producthunt.com' + makers_url if makers_url.startswith('/') else makers_url
                
                print(f"[INFO] Navigating to Team page: {makers_url}")
                page.get(makers_url)
                # Wait for Cloudflare challenge to complete
                max_wait = 60  # Increase to 60 seconds
                waited = 0
                while waited < max_wait:
                    page.wait(3)
                    waited += 3
                    title = page.title
                    html = page.html[:500] if page.html else ""
                    # Check if challenge is still active
                    if title and "请稍候" not in title and "Just a moment" not in title and "challenge" not in html.lower():
                        print(f"[DEBUG] Cloudflare challenge passed after {waited}s")
                        break
                    if waited % 6 == 0:  # Print every 6 seconds
                        print(f"[DEBUG] Waiting for Cloudflare challenge... ({waited}s)")
                
                page.wait(3)  # Additional wait for content load
                # Scroll to load content
                page.scroll.to_bottom()
                page.wait(2)
                print(f"[DEBUG] Current URL: {page.url}")
                print(f"[DEBUG] Page title: {page.title}")
                team_clicked = True
            else:
                # Try constructing makers URL directly (format: product_url + "/makers")
                print(f"[DEBUG] Could not find /makers link, trying to construct URL directly...")
                if product_url and '/products/' in product_url:
                    # Remove query params and append /makers
                    base_url = product_url.split('?')[0]
                    if not base_url.endswith('/makers'):
                        makers_url = base_url + '/makers'
                        try:
                            print(f"[INFO] Trying constructed URL: {makers_url}")
                            page.get(makers_url, timeout=30)
                            # Wait for Cloudflare challenge to complete
                            max_wait = 60  # Increase to 60 seconds
                            waited = 0
                            while waited < max_wait:
                                page.wait(3)
                                waited += 3
                                title = page.title
                                html = page.html[:500] if page.html else ""
                                # Check if challenge is still active
                                if title and "请稍候" not in title and "Just a moment" not in title and "challenge" not in html.lower():
                                    print(f"[DEBUG] Cloudflare challenge passed after {waited}s")
                                    break
                                if waited % 6 == 0:  # Print every 6 seconds
                                    print(f"[DEBUG] Waiting for Cloudflare challenge... ({waited}s)")
                            
                            page.wait(3)  # Additional wait for content load
                            # Scroll to load content
                            page.scroll.to_bottom()
                            page.wait(2)
                            print(f"[DEBUG] Current URL: {page.url}")
                            print(f"[DEBUG] Page title: {page.title}")
                            # Check if we're on a valid makers page
                            if '/makers' in page.url:
                                team_clicked = True
                        except Exception as e:
                            print(f"[DEBUG] Failed to access constructed URL: {e}")
        
        if not team_clicked:
            print(f"[WARN] Team page not accessible")
        
        # DEBUG: Check page content
        print(f"[DEBUG] Page title: {page.title}")
        print(f"[DEBUG] Page URL: {page.url}")
        
        # DEBUG: Check all links on page
        try:
            all_links = page.eles('css:a')
            print(f"[DEBUG] Total links on page: {len(all_links)}")
            # Print first 10 links for debugging
            for i, link in enumerate(all_links[:10]):
                try:
                    href = link.attr('href') or ''
                    text = link.text.strip() if link.text else ''
                    print(f"[DEBUG]   Link {i+1}: href='{href[:50]}', text='{text[:30]}'")
                except:
                    pass
        except Exception as e:
            print(f"[DEBUG] Error getting links: {e}")
        
        # Extract team member links (only from team section after clicking)
        team_members = []
        seen_hrefs = set()
        
        # Try multiple selectors for team members
        links = []
        # Strategy 1: Specific selector with font-semibold class
        try:
            links = page.eles('css:a[href^="/@"].font-semibold')
            print(f"[DEBUG] Found {len(links)} team member links with font-semibold class")
        except Exception as e:
            print(f"[DEBUG] Error with font-semibold selector: {e}")
            pass
        
        # Strategy 2: More generic selector if first one fails
        if len(links) == 0:
            try:
                links = page.eles('css:a[href^="/@"]')
                print(f"[DEBUG] Found {len(links)} links starting with /@")
            except:
                pass
        
        # Strategy 3: Try finding by text pattern (user profiles)
        if len(links) == 0:
            try:
                # Look for links that contain user profile patterns
                all_links = page.eles('css:a')
                for link in all_links:
                    href = link.attr('href') or ''
                    if href.startswith('/@') and len(href) > 2:
                        links.append(link)
                print(f"[DEBUG] Found {len(links)} team member links via pattern matching")
            except Exception as e:
                print(f"[DEBUG] Error in pattern matching: {e}")
                pass
        
        # DEBUG: Check HTML for team-related content
        if len(links) == 0:
            try:
                html_snippet = page.html[:2000]  # First 2000 chars
                print(f"[DEBUG] Page HTML snippet (first 2000 chars): {html_snippet}")
                # Check for common team-related keywords
                if 'team' in html_snippet.lower() or 'maker' in html_snippet.lower():
                    print(f"[DEBUG] Found 'team' or 'maker' in HTML")
            except Exception as e:
                print(f"[DEBUG] Error getting HTML: {e}")
        
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
                    print(f"[DEBUG] Found: {text}")
            except:
                continue
        
        print(f"[SUCCESS] Extracted {len(team_members)} team members")
        return team_members, company_info
        
    except Exception as e:
        print(f"[ERROR] Failed to scrape {product_url}: {e}")
        return [], ""


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Scrape ProductHunt team members with DrissionPage")
    parser.add_argument("--url", help="Single product URL to scrape (for testing)")
    parser.add_argument("--limit", type=int, help="Limit number of records to process")
    parser.add_argument("--output-json", type=str, help="Save results to JSON file")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--latest-week", action="store_true", help="Only process records from the latest week")
    args = parser.parse_args()
    
    cfg = load_config()
    
    # Parse cookies
    cookies = parse_cookies(cfg.get("PH_COOKIES", ""))
    if cookies:
        print(f"[INFO] Using {len(cookies)} cookies for authentication")
    
    # Setup DrissionPage browser
    co = ChromiumOptions()
    if args.headless:
        co.headless()
    
    page = ChromiumPage(addr_or_opts=co)
    
    # Set cookies
    if cookies:
        page.get('https://www.producthunt.com')
        page.set.cookies(cookies)
    
    # Single URL mode (for testing)
    if args.url:
        print(f"[INFO] Testing single URL: {args.url}")
        team_members, company_info = scrape_team_members_drission(args.url, page)
        print(f"[RESULT] Team members: {team_members}")
        print(f"[RESULT] Company Info: {company_info}")
        page.quit()
        return
    
    # Batch mode - fetch from Feishu
    token = get_feishu_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    if not token:
        print("[ERROR] Failed to get Feishu token")
        page.quit()
        return
    
    # Get timezone from config or use default
    timezone = cfg.get("TIMEZONE", "Asia/Shanghai")
    
    print("[INFO] Fetching records from Feishu Bitable...")
    # If latest_week_only causes timeout, fetch all records first then filter locally
    if args.latest_week:
        print("[INFO] Fetching all records first, then filtering for latest week locally...")
        all_records = fetch_feishu_records(
            token, 
            cfg["FEISHU_TABLE_APP_ID"], 
            cfg["FEISHU_TABLE_ID"],
            latest_week_only=False,  # Fetch all first
            timezone=timezone
        )
        print(f"[INFO] Fetched {len(all_records)} total records")
        
        # Filter locally for latest week
        tz = pytz.timezone(timezone)
        today = datetime.now(tz).date()
        iso_weekday = today.isoweekday()
        monday = today if iso_weekday == 1 else (today - timedelta(days=iso_weekday - 1))
        target_week_str = monday.strftime("%Y/%m/%d")
        print(f"[INFO] Filtering for latest week: {target_week_str}")
        
        # We need to fetch week info from Feishu for each record
        # For now, let's try the API approach but with better error handling
        to_process = fetch_feishu_records(
            token, 
            cfg["FEISHU_TABLE_APP_ID"], 
            cfg["FEISHU_TABLE_ID"],
            latest_week_only=True,
            timezone=timezone
        )
        if len(to_process) == 0 and len(all_records) > 0:
            print("[WARN] Week filtering via API failed, but we have records. Processing all records...")
            print("[WARN] Note: This will process all records, not just latest week")
            to_process = all_records[:100]  # Limit to 100 to avoid processing too many
    else:
        to_process = fetch_feishu_records(
            token, 
            cfg["FEISHU_TABLE_APP_ID"], 
            cfg["FEISHU_TABLE_ID"],
            latest_week_only=False,
            timezone=timezone
        )
    
    if args.latest_week:
        print(f"[INFO] Found {len(to_process)} records from latest week")
    else:
        print(f"[INFO] Found {len(to_process)} records")
    # Process records in order (Feishu order)
    # User requested "from back to front" (latest first)
    to_process.reverse()
    
    # Filter for specific target products if requested
    target_names = []
    
    if target_names:
        print(f"[INFO] Filtering for {len(target_names)} specific products...")
        to_process = [p for p in to_process if p['product_name'] in target_names]
        print(f"[INFO] Found {len(to_process)} matching records")
    
    # Load existing JSON if exists to preserve history/order
    json_file = args.output_json or "team_members.json"
    existing_data = []
    existing_ids = set()
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                existing_ids = {item['record_id'] for item in existing_data}
                print(f"[INFO] Loaded {len(existing_data)} existing records from {json_file}")
        except Exception as e:
            print(f"[WARN] Failed to load existing JSON: {e}")
    
    # Note: We don't filter out records based on JSON cache anymore
    # because Feishu might still have empty fields (previous scraping might have failed)
    # We'll process all records from Feishu that have empty team_members or Company_Info
    print(f"[INFO] Will process {len(to_process)} records from Feishu (ignoring JSON cache)")
    
    # Apply limit (default 50 if not specified)
    limit = args.limit if args.limit else 50
    if limit:
        to_process = to_process[:limit]
        print(f"[INFO] Limited to {len(to_process)} records (Batch size: {limit})")
    
    if not to_process:
        print("[INFO] No new records to process")
        page.quit()
        return
    
    # Map existing data by record_id for easy update
    data_map = {item['record_id']: item for item in existing_data}
    
    # Scrape team members
    updates_buffer = []
    
    print(f"[INFO] Starting scrape of {len(to_process)} products...")
    
    # Helper to get a fresh browser page
    def get_page(headless=True):
        co = ChromiumOptions()
        if headless:
            co.headless()
        p = ChromiumPage(addr_or_opts=co)
        if cookies:
            p.get('https://www.producthunt.com')
            p.set.cookies(cookies)
        return p

    # Initial browser setup (already done in main, but we might need to restart)
    # We'll use the existing 'page' variable, but update it if needed
    
    request_count = 0
    
    for idx, item in enumerate(to_process):
        print(f"\n[{idx+1}/{len(to_process)}] Processing: {item['product_name']}")
        
        # Restart browser every 20 requests or if it's dead
        if request_count > 20:
            print("[INFO] Restarting browser to free memory...")
            try:
                page.quit()
            except:
                pass
            page = get_page(args.headless)
            request_count = 0
            
        try:
            team_members, company_info = scrape_team_members_drission(item["url"], page)
            request_count += 1
        except Exception as e:
            print(f"[ERROR] Scraper crashed: {e}")
            print("[INFO] Attempting to restart browser and retry...")
            try:
                page.quit()
            except:
                pass
            page = get_page(args.headless)
            request_count = 0
            try:
                team_members, company_info = scrape_team_members_drission(item["url"], page)
            except Exception as e2:
                print(f"[ERROR] Retry failed: {e2}")
                team_members = []
                company_info = ""
        
        # Update local data structure
        record_data = {
            "record_id": item["record_id"],
            "product_name": item["product_name"],
            "url": item["url"],
            "team_members": team_members,
            "company_info": company_info,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        data_map[item["record_id"]] = record_data
        
        # Save to JSON immediately (incremental save)
        try:
            save_list = list(data_map.values())
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(save_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to save JSON: {e}")
            
        # Prepare update fields
        update_fields = {}
        if team_members:
            update_fields["team_members"] = team_members
        if company_info:
            # Feishu Link field format
            update_fields["Company_Info"] = {"text": company_info, "link": company_info}
            
        if update_fields:
            updates_buffer.append((item["record_id"], update_fields))
            if team_members:
                print(f"[SUCCESS] Found {len(team_members)} team members")
            if company_info:
                print(f"[SUCCESS] Found Company Info: {company_info}")
        else:
            print(f"[WARN] No data found for {item['product_name']}")
        
        # Sync to Feishu every 10 records or if it's the last one
        if len(updates_buffer) >= 10 or idx == len(to_process) - 1:
            if updates_buffer:
                print(f"[INFO] Auto-syncing {len(updates_buffer)} records to Feishu...")
                batch_update_feishu(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], updates_buffer)
                updates_buffer = [] # Clear buffer after sync
            
        # Be nice - wait between requests
        if idx < len(to_process) - 1:
            time.sleep(2)
    
    try:
        page.quit()
    except:
        pass
    
    print(f"\n{'='*50}")
    print(f"Scraping completed!")
    print(f"Processed: {len(to_process)} products")
    print(f"Data saved to: {json_file}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
