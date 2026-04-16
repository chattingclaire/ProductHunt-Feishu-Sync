#!/usr/bin/env python3
"""
Test DrissionPage for ProductHunt scraping
"""
from DrissionPage import ChromiumPage
import time

def test_drission():
    # Create browser
    page = ChromiumPage()
    
    # Set cookies
    page.get('https://www.producthunt.com')
    page.set.cookies([
        {"name": "_producthunt_session_production", "value": "icxS4Gu8V39R8hgPnVgbcm%2BR9cHhYUa3T15ewFuks%2FH3L2zvg%2BgAvgmoT4jd1dhg8oI%2BV3RpTJgaKUbFRkYWssEvviNX8LeTnisFw3QJhkcU8NFAFdCC9by3pfxRoIyIWzsRLg3tWivkBYFnDpUpY%2F%2F3Esc%2BxMqqgbxvgAXuapWJUeJtWXXDz9EVc0M2qlLA6GXI8uZQOeAFGQVhnqc1bDe3H6P0iKzR%2BRHcut%2F3fCj9jkYh3HZAiQiDyfUelSAvPEumeZgUc53gYOw9f%2FtF4Iw4S%2F6mGAISvCpRgNvjPQ4gteJ%2BggK6yFLgjPCNML6lKRapILm6capfR%2BqMakQUFYXg852dzs38xUtgDTwE1hz6pao7EEoD0YMvPISJLzvwBpAN2jnmZgHFgxyPzt9UDc0sV11Vx9B1YcD5J1X8pphA9s1ZzGxtlRJ7Y3bnRHOblKYPgHiSixGGXUyFCD43vCJfYuYQ1uu6RNyDPjk%3D--%2BdlasyTOdgu9yeJv--5eiOtjoOMvXZvFPlqEO0Rw%3D%3D", "domain": ".producthunt.com"},
        {"name": "cf_clearance", "value": "FMqcVlAObif4Pi9TsV0gC9nT1LjQMAEVMcVokSLPgzc-1764040897-1.2.1.1-Awmpfi48hiGJWreI6S6mvCYJDMRd2ixyApVEVLvOu10H6DoL7QMNVhT0OGw9IPGVIdX5N0RD_eXTlvtzckmtdtWMsvqSQzitArcvD1QIm103nal4aS3LC3Y4D_iHuevtv34pbxddbIuUScts3pjuYCzsfyCroHSUNwrGCtrAlb7G9lY4kHmOLWbpGvhRNHfOUvVPXbO4taV6j36Q_nodqBzdil24Wwl9UIa8uy58ELgLIx96Lu1IrVtv.T.plkmb", "domain": ".producthunt.com"},
        {"name": "__cf_bm", "value": "eSHgN7lmHjoIsWEAynNJtZCni8fiiay4hDgnZkvb7Nw-1764041122-1.0.1.1-kiNDb8gHWZGI6dMLiI5TIy2Tl1uUb1ZcjQWIFKElN4iw4kThEDF7uTaVXcWVjOua7T0rbOD2BiBe.WQA_9kqQAZG1Zr6DWlk8FdoR6qC1vA", "domain": ".producthunt.com"},
    ])
    
    print("Navigating to product page...")
    page.get('https://www.producthunt.com/products/extract-by-firecrawl')
    
    print("Waiting 5 seconds...")
    time.sleep(5)
    
    print("Looking for Team button...")
    team_buttons = page.eles('css:span.text-sm.font-semibold')
    for btn in team_buttons:
        if 'Team' in btn.text:
            print(f"Found Team button: {btn.text}")
            print("Clicking...")
            btn.click()
            print("Waiting 10 seconds after click...")
            time.sleep(10)
            break
    
    print("\nLooking for team member links...")
    links = page.eles('css:a[href^="/@"]')
    print(f"Found {len(links)} links with href starting with /@")
    
    team_members = []
    for link in links:
        href = link.attr('href')
        text = link.text.strip()
        if text and href:
            print(f"  - {text} ({href})")
            if text not in team_members:
                team_members.append(text)
    
    print(f"\n✅ Extracted {len(team_members)} unique team members:")
    for member in team_members:
        print(f"  - {member}")
    
    page.quit()
    return team_members

if __name__ == "__main__":
    test_drission()
