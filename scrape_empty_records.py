import os
import time
import requests
from dotenv import load_dotenv
from wokflow import (
    load_config, 
    feishu_access_token, 
    feishu_list_all_records, 
    feishu_batch_update,
    augment_from_weekly_page
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
    
    # Filter for empty description or tags
    empty_records = []
    for r in records:
        fields = r.get("fields", {})
        desc = fields.get("description", "")
        tags = fields.get("Launch_tags", [])
        
        # Check if description is missing or tags are empty
        if not desc or not tags:
            empty_records.append(r)
            
    print(f"[INFO] Found {len(empty_records)} records with missing description or tags.")
    
    if not empty_records:
        print("[INFO] No empty records to process.")
        return

    # Initialize DrissionPage session if needed (augment_from_weekly_page uses it internally or we can pass one)
    # Actually augment_from_weekly_page takes a list of products.
    # But here we have individual records. We can reuse the scraping logic.
    # Let's use a simplified version of what wokflow.py does for augmentation.
    
    # We need to construct "product" dicts from Feishu records to pass to augmentation
    products_to_augment = []
    for r in empty_records:
        fields = r.get("fields", {})
        # We need 'url' and 'id' (PH_Id) for augmentation
        p_url_raw = fields.get("PH_Link", "")
        if isinstance(p_url_raw, dict):
            p_url = p_url_raw.get("link", "")
        else:
            p_url = str(p_url_raw) if p_url_raw else ""
            
        p_id = fields.get("PH_Id", "")
        
        if not p_url:
            print(f"[WARN] Record {r['record_id']} has no PH_Link, skipping.")
            continue
            
        products_to_augment.append({
            "id": p_id,
            "url": p_url,
            "record_id": r["record_id"], # Keep track of Feishu record ID
            "name": fields.get("Product Name", ""),
            "tagline": fields.get("PH_Brief", ""),
            "description": fields.get("description", ""),
            "topics": fields.get("Launch_tags", []),
            "website": fields.get("Company Website", ""),
            "makers": fields.get("Maker_list", [])
        })
        
    print(f"[INFO] Processing {len(products_to_augment)} products...")
    
    print(f"[INFO] Processing {len(products_to_augment)} products...")
    
    # Use augment_with_product_pages to scrape individual pages
    # This function is defined in wokflow.py but not exported in __all__ (if it exists).
    # We need to import it. I checked and it is at module level.
    from wokflow import augment_with_product_pages
    
    # augment_with_product_pages(products, session, drission_page)
    # We can pass None for session and drission_page to let it create them.
    
    augmented = augment_with_product_pages(products_to_augment)
    
    # Now sync back to Feishu
    print("[INFO] Syncing updates to Feishu...")
    updates = []
    for p in augmented:
        record_id = p.get("record_id")
        if not record_id:
            continue
            
        fields_to_update = {}
        if p.get("description"):
            fields_to_update["description"] = p["description"]
        if p.get("topics"):
            fields_to_update["Launch_tags"] = p["topics"]
        if p.get("website"):
            fields_to_update["Company Website"] = p["website"]
        if p.get("makers"):
            fields_to_update["Maker_list"] = p["makers"]
            
        if fields_to_update:
            updates.append((record_id, fields_to_update))
            
    if updates:
        # Batch update in chunks of 50 (Feishu limit)
        chunk_size = 50
        for i in range(0, len(updates), chunk_size):
            chunk = updates[i:i+chunk_size]
            print(f"[INFO] Updating batch {i//chunk_size + 1} ({len(chunk)} records)...")
            feishu_batch_update(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], chunk)
            time.sleep(0.5)
            
    print("[INFO] Done.")

if __name__ == "__main__":
    main()
