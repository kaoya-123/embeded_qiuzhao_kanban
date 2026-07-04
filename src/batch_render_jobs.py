"""
批量抓取 小米/OPPO/汇川/华为/比亚迪/海康 的岗位列表页。
渲染后保存正文到 data/job_pages/。
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGETS = {
    "小米":   "https://hr.xiaomi.com/campus",
    "OPPO":   "https://careers.oppo.com/campus",
    "汇川":   "https://inovance.zhiye.com/campus",
    "华为":   "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html?v=20241208",
    "比亚迪": "https://job.byd.com/",
    "海康":   "https://campushr.hikvision.com/",
}
OUT = Path(__file__).resolve().parents[1] / "data" / "job_pages"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    for name, url in TARGETS.items():
        print(f"  {name} ...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            # 尝试点击"在招职位/岗位"等按钮
            for label in ["全部职位", "校园招聘", "在招职位", "职位", "岗位", "校招职位", "查看全部"]:
                try:
                    loc = page.get_by_text(label, exact=False).first
                    if loc.count():
                        loc.click(timeout=2000)
                        page.wait_for_timeout(4000)
                except Exception:
                    pass
            text = page.locator("body").inner_text(timeout=20000)
            (OUT / f"{name}.txt").write_text(
                "TITLE: " + page.title() + "\nURL: " + page.url + "\n\n" + text,
                encoding="utf-8"
            )
            print(f"  {name} ok {len(text)} chars, url={page.url}")
        except Exception as e:
            (OUT / f"{name}.txt").write_text("ERR: " + repr(e), encoding="utf-8")
            print(f"  {name} err {repr(e)}")
    browser.close()
print("done")
