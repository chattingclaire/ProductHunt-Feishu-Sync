#!/usr/bin/env python3
"""Quick test to see what's actually on the page after clicking Team"""
from playwright.sync_api import sync_playwright
import time

url = "https://www.producthunt.com/products/extract-by-firecrawl"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    # Add cookies
    page.context.add_cookies([
        {"name": "_producthunt_session_production", "value": "icxS4Gu8V39R8hgPnVgbcm%2BR9cHhYUa3T15ewFuks%2FH3L2zvg%2BgAvgmoT4jd1dhg8oI%2BV3RpTJgaKUbFRkYWssEvviNX8LeTnisFw3QJhkcU8NFAFdCC9by3pfxRoIyIWzsRLg3tWivkBYFnDpUpY%2F%2F3Esc%2BxMqqgbxvgAXuapWJUeJtWXXDz9EVc0M2qlLA6GXI8uZQOeAFGQVhnqc1bDe3H6P0iKzR%2BRHcut%2F3fCj9jkYh3HZAiQiDyfUelSAvPEumeZgUc53gYOw9f%2FtF4Iw4S%2F6mGAISvCpRgNvjPQ4gteJ%2BggK6yFLgjPCNML6lKRapILm6capfR%2BqMakQUFYXg852dzs38xUtgDTwE1hz6pao7EEoD0YMvPISJLzvwBpAN2jnmZgHFgxyPzt9UDc0sV11Vx9B1YcD5J1X8pphA9s1ZzGxtlRJ7Y3bnRHOblKYPgHiSixGGXUyFCD43vCJfYuYQ1uu6RNyDPjk%3D--%2BdlasyTOdgu9yeJv--5eiOtjoOMvXZvFPlqEO0Rw%3D%3D", "domain": ".producthunt.com", "path": "/"},
    ])
    
    print("Navigating...")
    page.goto(url)
    time.sleep(3)
    
    print("Looking for Team button...")
    try:
        team_btn = page.locator('span.text-sm.font-semibold:has-text("Team")').first
        if team_btn.is_visible():
            print("Found Team button! Clicking...")
            team_btn.click()
            print("Waiting 15 seconds...")
            time.sleep(15)
            
            # Take screenshot
            page.screenshot(path="/tmp/after_team_click.png")
            print("Screenshot saved to /tmp/after_team_click.png")
            
            # Get HTML
            html = page.content()
            with open("/tmp/page_html.html", "w") as f:
                f.write(html)
            print("HTML saved to /tmp/page_html.html")
            
            # Try to find links
            all_links = page.locator('a[href^="/@"]').all()
            print(f"\nFound {len(all_links)} links starting with /@")
            for i, link in enumerate(all_links[:10]):
                try:
                    href = link.get_attribute("href")
                    text = link.inner_text()
                    print(f"  {i+1}. {href} -> {text}")
                except:
                    pass
        else:
            print("Team button not visible")
    except Exception as e:
        print(f"Error: {e}")
    
    input("\nPress Enter to close browser...")
    browser.close()
