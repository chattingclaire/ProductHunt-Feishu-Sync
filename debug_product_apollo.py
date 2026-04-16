from DrissionPage import ChromiumPage, ChromiumOptions
import json
import re
import time

def main():
    url = "https://www.producthunt.com/posts/cybercut-ai"
    print(f"Fetching {url}...")
    
    co = ChromiumOptions()
    # co.headless()
    page = ChromiumPage(addr_or_opts=co)
    page.get(url)
    page.wait(5)
    
    html = page.html
    apollo_re = re.compile(r'window\[Symbol\.for\("ApolloSSRDataTransport"\)\] \?\?= \[\]\)\.push\((.*?)\);', re.S)
    m_apollo = apollo_re.search(html)
    
    if m_apollo:
        print("Found Apollo data.")
        try:
            json_str = m_apollo.group(1)
            json_str = json_str.replace("undefined", "null")
            data, _ = json.JSONDecoder().raw_decode(json_str)
            # Save to file for inspection
            with open("debug_product_apollo.json", "w") as f:
                json.dump(data, f, indent=2)
            print("Saved Apollo data to debug_product_apollo.json")
            
            if "rehydrate" in data:
                rehydrate = data["rehydrate"]
                for key, val in rehydrate.items():
                    # Look for Post structure
                    if val and "data" in val and "post" in val["data"]:
                        post = val["data"]["post"]
                        print(f"Found Post node. Description: {post.get('description')}")
        except Exception as e:
            print(f"Error parsing JSON: {e}")
    else:
        print("Apollo data not found.")
        
    page.quit()

if __name__ == "__main__":
    main()
