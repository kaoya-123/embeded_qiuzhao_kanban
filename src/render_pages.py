from pathlib import Path
from playwright.sync_api import sync_playwright

URLS = {
    "dji": "https://careers.dji.com/zh-CN/campus",
    "oppo": "https://careers.oppo.com/campus",
    "vivo": "https://hr.vivo.com/wt/vivo/web/index/campus",
    "inovance": "https://inovance.zhiye.com/",
    "huawei": "https://career.huawei.com/reccampportal/portal5/index.html",
}
OUT = Path(__file__).resolve().parents[1] / "data" / "rendered"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    for name, url in URLS.items():
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)
            text = page.locator("body").inner_text(timeout=15000)
            (OUT / f"{name}.txt").write_text("TITLE: " + page.title() + "\nURL: " + page.url + "\n\n" + text, encoding="utf-8")
            print(name, "ok", len(text))
        except Exception as e:
            (OUT / f"{name}.txt").write_text("ERR: " + repr(e), encoding="utf-8")
            print(name, "err", repr(e))
    browser.close()
