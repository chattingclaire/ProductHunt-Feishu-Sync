from DrissionPage import ChromiumPage
import time

def inspect_page(url_suffix):
    page = ChromiumPage()
    url = f"https://www.producthunt.com/products/{url_suffix}/makers"
    print(f"Navigating to {url}")
    page.get(url)
    time.sleep(5)
    
    print(f"--- Inspecting {url_suffix} ---")
    links = page.eles('css:a[href^="/@"]')
    print(f"Found {len(links)} links with /@")
    for i, link in enumerate(links[:5]):
        print(f"  {i}: Text='{link.text}', Class='{link.attr('class')}', Href='{link.attr('href')}'")
        
    if len(links) == 0:
        print("  Dumping first 10 links of ANY type:")
        all_links = page.eles('tag:a')
        for i, link in enumerate(all_links[:10]):
            print(f"  {i}: Text='{link.text}', Href='{link.attr('href')}'")
            
    page.quit()

if __name__ == "__main__":
    inspect_page("extract-by-firecrawl") # Working
    inspect_page("usage4claude")         # Failing
