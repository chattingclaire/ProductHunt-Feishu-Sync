#!/usr/bin/env python3
"""
Import team members from JSON file to Feishu Bitable
"""
import json
import os
import sys
import time
from typing import List, Dict
from dotenv import load_dotenv
import requests

# Add parent directory to path to import from scrape_team_members
sys.path.insert(0, os.path.dirname(__file__))
from scrape_team_drission import get_feishu_token, batch_update_feishu, load_config

def import_to_feishu(json_file: str):
    """Import team members from JSON file to Feishu"""
    
    if not os.path.exists(json_file):
        print(f"[ERROR] File not found: {json_file}")
        return
    
    # Load JSON data
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not data:
        print("[INFO] No data to import")
        return
        
    print(f"[INFO] Loaded {len(data)} records from {json_file}")
    
    # Filter out records with no data to update
    updates = []
    for item in data:
        fields = {}
        if item.get('team_members'):
            fields['team_members'] = item['team_members']
        if item.get('company_info'):
            # Feishu Link field format
            url = item['company_info']
            fields['Company_Info'] = {"text": url, "link": url}
            
        if fields:
            updates.append((item['record_id'], fields))
            
    if not updates:
        print("[INFO] No records with team members to update")
        return
        
    print(f"[INFO] Found {len(updates)} records to update")
    
    # Get Feishu credentials
    cfg = load_config()
    
    # Get token
    token = get_feishu_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    if not token:
        print("[ERROR] Failed to get Feishu token")
        return
    
    # Batch update in chunks of 50
    chunk_size = 50
    for i in range(0, len(updates), chunk_size):
        chunk = updates[i:i+chunk_size]
        print(f"[INFO] Updating chunk {i//chunk_size + 1} ({len(chunk)} records)...")
        batch_update_feishu(token, cfg["FEISHU_TABLE_APP_ID"], cfg["FEISHU_TABLE_ID"], chunk)
        time.sleep(0.5)
        
    print(f"[SUCCESS] Import completed! Updated {len(updates)} records")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Import scraped team members to Feishu")
    parser.add_argument("json_file", help="JSON file with scraped data")
    args = parser.parse_args()
    
    import_to_feishu(args.json_file)
