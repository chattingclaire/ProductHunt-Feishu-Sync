import os
import time
import requests
import pytz
from datetime import timedelta
from dotenv import load_dotenv
from wokflow import (
    load_config, 
    feishu_access_token, 
    feishu_list_all_records, 
    feishu_batch_update,
    fetch_weekly_page,
    parse_weekly_products,
    compute_weekly_url
)
from DrissionPage import ChromiumPage, ChromiumOptions

# Load env
load_dotenv()

def main():
    cfg = load_config()
    if not (cfg["FEISHU_APP_ID"] and cfg["FEISHU_APP_SECRET"] and cfg["FEISHU_TABLE_APP_ID"] and cfg["FEISHU_TABLE_ID"]):
        print("[ERROR] Missing Feishu configuration.")
        return

    print("[INFO] Authenticating with Feishu...")
    token = feishu_access_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    
    print("[INFO] Fetching all records from Feishu...")
    records = feishu_list_all_records(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"])
    print(f"[INFO] Found {len(records)} records.")
    
    # Filter for empty description - focus on latest week
    empty_records = []
    # Get latest week date string
    from datetime import datetime
    import pytz
    tz = pytz.timezone(cfg["TIMEZONE"])
    today = datetime.now(tz).date()
    iso_weekday = today.isoweekday()
    monday = today if iso_weekday == 1 else (today - timedelta(days=iso_weekday - 1))
    target_week = monday.strftime("%Y/%m/%d")
    print(f"[INFO] Target week: {target_week}")
    
    for r in records:
        fields = r.get("fields", {})
        # Try both "Description" and "description" for compatibility
        desc = fields.get("Description", "") or fields.get("description", "")
        
        # Check Week_Range field to filter for 1130 week
        week_range = fields.get("Week_Range", "")
        week_str = ""
        if isinstance(week_range, (int, float)):
            # It's a timestamp, convert to date string
            from datetime import datetime
            try:
                dt = datetime.fromtimestamp(week_range / 1000)
                week_str = dt.strftime("%Y/%m/%d")
            except:
                pass
        elif isinstance(week_range, str):
            week_str = week_range
        
        # Focus on 1130 week records that are missing description
        is_target_week = target_week in week_str or week_str.startswith("2025/11/30")
        
        if is_target_week and not desc:
            empty_records.append(r)
    
    print(f"[INFO] Found {len(empty_records)} records from {target_week} week with missing description.")
    
    if not empty_records:
        print("[INFO] No empty records to process.")
        return

    # Fetch weekly page data for latest week
    weekly_url = compute_weekly_url(cfg["TIMEZONE"], week_offset=0)
    
    # Try GraphQL API first if token is available (gets complete data with pagination)
    ph_token = cfg.get("PH_BEARER_TOKEN", "").strip()
    if ph_token:
        print(f"[INFO] Using GraphQL API to fetch complete weekly data...")
        from wokflow import fetch_week_via_graphql, week_start_end, parse_week_from_url
        parsed = parse_week_from_url(weekly_url)
        if parsed:
            year, week_no = parsed
            tz = pytz.timezone(cfg["TIMEZONE"])
            start_dt, end_dt = week_start_end(year, week_no, cfg["TIMEZONE"])
            products = fetch_week_via_graphql(ph_token, start_dt, end_dt)
            print(f"[INFO] GraphQL API returned {len(products)} products (complete data with pagination)")
        else:
            print(f"[WARN] Could not parse weekly URL, falling back to page scraping")
            data = fetch_weekly_page(weekly_url)
            products = parse_weekly_products(data)
            print(f"[INFO] Parsed {len(products)} products from weekly page (first page only)")
    else:
        print(f"[INFO] No PH_BEARER_TOKEN found, using page scraping (may be incomplete)")
        print(f"[INFO] Fetching weekly page: {weekly_url}")
        data = fetch_weekly_page(weekly_url)
        products = parse_weekly_products(data)
        print(f"[INFO] Parsed {len(products)} products from weekly page (first page only, hasNextPage=True means more available)")
    
    # Build index of products by ID and Name/Slug
    by_id = {str(p.get("id")): p for p in products if p.get("id")}
    by_name = {p.get("name").lower(): p for p in products if p.get("name")}
    
    # Identify records that need update
    records_to_update = []
    products_to_scrape = []
    
    for r in empty_records:
        fields = r.get("fields", {})
        record_id = r["record_id"]
        
        p_id = str(fields.get("PH_Id", ""))
        # Try both "Product_Name" and "Product Name" for compatibility
        p_name_raw = fields.get("Product_Name", "") or fields.get("Product Name", "")
        # Handle Product_Name field which might be a list of text objects
        if isinstance(p_name_raw, list) and len(p_name_raw) > 0:
            p_name = p_name_raw[0].get("text", "").lower() if isinstance(p_name_raw[0], dict) else str(p_name_raw[0]).lower()
        else:
            p_name = str(p_name_raw).lower()
        
        # Get URL for scraping
        ph_link = fields.get("PH_Link", "")
        product_url = ""
        if isinstance(ph_link, dict):
            product_url = ph_link.get("link", "")
        elif isinstance(ph_link, str):
            product_url = ph_link
        
        match = by_id.get(p_id)
        if not match and p_name:
            match = by_name.get(p_name)
        
        # If found in weekly API, use that data
        if match:
            # Check if we need to scrape description (if missing in match)
            # My debug showed description is missing in Apollo data.
            # So we MUST scrape if description is missing in Feishu.
            # Try both "Description" and "description" for compatibility
            current_desc = fields.get("Description", "") or fields.get("description", "")
            if not current_desc:
                 # We need to scrape this product
                 # Add record_id and URL to match for tracking
                 match["record_id"] = record_id
                 if not match.get("url") and product_url:
                     match["url"] = product_url
                 products_to_scrape.append(match)
            else:
                 # Just update topics if needed
                 if not fields.get("Launch_tags") and match.get("topics"):
                     records_to_update.append((record_id, {"Launch_tags": match.get("topics")}))
        else:
            # Not found in weekly API, but we still need to scrape description
            # Create a minimal product dict for scraping
            if product_url:
                products_to_scrape.append({
                    "record_id": record_id,
                    "name": p_name,
                    "id": p_id,
                    "url": product_url
                })
    
    print(f"[INFO] Found {len(products_to_scrape)} products needing description scraping.")
    
    if products_to_scrape:
        from wokflow import augment_with_product_pages
        print("[INFO] Scraping product pages for description...")
        scraped_products = augment_with_product_pages(products_to_scrape)
        
        for p in scraped_products:
            record_id = p.get("record_id")
            fields_to_update = {}
            if p.get("description"):
                # Use "Description" (capital D) to match Feishu field name
                fields_to_update["Description"] = p.get("description")
            if p.get("topics"):
                fields_to_update["Launch_tags"] = p.get("topics")
            
            if fields_to_update:
                records_to_update.append((record_id, fields_to_update))

    print(f"[INFO] Prepared {len(records_to_update)} updates.")
    
    if records_to_update:
        # Batch update in chunks of 50
        chunk_size = 50
        for i in range(0, len(records_to_update), chunk_size):
            chunk = records_to_update[i:i+chunk_size]
            print(f"[INFO] Updating batch {i//chunk_size + 1} ({len(chunk)} records)...")
            feishu_batch_update(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], chunk)
            time.sleep(0.5)
            
    print("[INFO] Done.")

if __name__ == "__main__":
    main()
