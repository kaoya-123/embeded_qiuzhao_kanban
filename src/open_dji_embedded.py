from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "dji_network"
url = "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/jobs"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":1200})
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    # locate text 嵌入式工程师 and click it
    try:
        loc = page.get_by_text("嵌入式工程师（上海）", exact=True).first
        loc.click(timeout=5000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print('click err', repr(e))
    text=page.locator('body').inner_text(timeout=20000)
    (OUT/'embedded_detail.txt').write_text('URL: '+page.url+'\nTITLE: '+page.title()+'\n\n'+text, encoding='utf-8')
    print('url', page.url, 'len', len(text))
    browser.close()
