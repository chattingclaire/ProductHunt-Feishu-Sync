from DrissionPage import ChromiumPage, ChromiumOptions
import time

def test_extraction(url):
    co = ChromiumOptions()
    # co.headless() # Run visible to see what happens
    page = ChromiumPage(addr_or_opts=co)
    
    print(f"Navigating to {url}")
    page.get(url)
    page.wait(5)
    
    print("Page title:", page.title)
    
    # Test Description
    print("--- Description ---")
    desc = None
    try:
        desc_elem = page.ele('css:meta[name="description"]', timeout=2)
        if desc_elem:
            print("Found meta[name='description']:", desc_elem.attr("content"))
            desc = desc_elem.attr("content")
        else:
            print("meta[name='description'] not found")
    except Exception as e:
        print("Error finding meta description:", e)
        
    if not desc:
        try:
            desc_elem = page.ele('css:meta[property="og:description"]', timeout=2)
            if desc_elem:
                print("Found meta[property='og:description']:", desc_elem.attr("content"))
                desc = desc_elem.attr("content")
            else:
                print("meta[property='og:description'] not found")
        except Exception as e:
            print("Error finding og description:", e)

    # Test Topics
    print("--- Topics ---")
    try:
        topic_links = page.eles('css:a[href^="/topics/"]')
        print(f"Found {len(topic_links)} topic links")
        for link in topic_links:
            if link.states.is_displayed:
                print("Topic:", link.text)
            else:
                print("Topic (hidden):", link.text)
    except Exception as e:
        print("Error finding topics:", e)
        
    page.quit()

if __name__ == "__main__":
    # Test with one of the products from the user's screenshot or logs
    test_extraction("https://www.producthunt.com/posts/cybercut-ai")
