from wokflow import fetch_weekly_page, parse_weekly_products, compute_weekly_url, load_config
import json

def main():
    cfg = load_config()
    weekly_url = compute_weekly_url(cfg["TIMEZONE"], week_offset=0)
    print(f"Fetching {weekly_url}...")
    
    data = fetch_weekly_page(weekly_url)
    
    # Inspect raw Apollo data structure for the first product
    if "rehydrate" in data:
        print("Found Apollo data.")
        rehydrate = data["rehydrate"]
        for key, val in rehydrate.items():
            if val and "data" in val and val["data"] and "homefeedItems" in val["data"]:
                edges = val["data"]["homefeedItems"].get("edges", [])
                if edges:
                    node = edges[0].get("node", {})
                    print("--- First Product Raw Node ---")
                    print(json.dumps(node, indent=2))
                    
                    print("\n--- Extracted Description ---")
                    print(f"Description: {node.get('description')}")
                    print(f"Tagline: {node.get('tagline')}")
                    break
    else:
        print("Apollo data not found or different structure.")

    # Check parsed products
    products = parse_weekly_products(data)
    print(f"\nParsed {len(products)} products.")
    if products:
        print("--- First Parsed Product ---")
        print(json.dumps(products[0], indent=2))

if __name__ == "__main__":
    main()
