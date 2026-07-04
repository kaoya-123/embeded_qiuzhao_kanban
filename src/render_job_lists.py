from pathlib import Path
from playwright.sync_api import sync_playwright
import re

PAGES = {
    "dji_jobs": "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/",
    "vivo_jobs": "https://hr-campus.vivo.com/",
    "inovance_jobs": "https://inovance.zhiye.com/campus",
    "huawei_jobs": "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html?v=20241208",
}
OUT = Path(__file__).resolve().parents[1] / "data" / "jobs"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    for name, url in PAGES.items():
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            # 尝试点击“全部/职位/岗位”等可能触发列表的元素
            for label in ["全部", "校招职位", "职位", "岗位", "查看岗位", "查看在招职位"]:
                try:
                    loc = page.get_by_text(label, exact=False).first
                    if loc.count():
                        loc.click(timeout=1500)
                        page.wait_for_timeout(3000)
                except Exception:
                    pass
            text = page.locator("body").inner_text(timeout=20000)
            (OUT / f"{name}.txt").write_text("TITLE: " + page.title() + "\nURL: " + page.url + "\n\n" + text, encoding="utf-8")
            print(name, "ok", len(text), page.url)
        except Exception as e:
            (OUT / f"{name}.txt").write_text("ERR: " + repr(e), encoding="utf-8")
            print(name, "err", repr(e))
    browser.close()
