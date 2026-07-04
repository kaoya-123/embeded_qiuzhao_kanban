from playwright.sync_api import sync_playwright
import re

URLS = {
    "大疆": "https://careers.dji.com/zh-CN/campus",
    "OPPO": "https://careers.oppo.com/campus",
    "vivo": "https://hr.vivo.com/wt/vivo/web/index/campus",
    "汇川": "https://inovance.zhiye.com/",
    "华为": "https://career.huawei.com/reccampportal/portal5/index.html",
}

KEY = re.compile(r".{0,30}(嵌入式|BSP|驱动|RTOS|Linux|MCU|单片机|车载|底层软件|软件工程师).{0,60}", re.I)
CAMPUS = re.compile(r"2027届|2027|27届|2026|校园招聘|校招|提前批", re.I)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    for name, url in URLS.items():
        print("="*20, name, "="*20)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(5000)
            text = page.locator("body").inner_text(timeout=10000)
            print("TITLE:", page.title())
            print("CAMPUS_HITS:", sorted(set(CAMPUS.findall(text)))[:20])
            hits = KEY.findall(text)
            lines = []
            for m in KEY.finditer(text):
                s = re.sub(r"\s+", " ", m.group(0)).strip()
                if s not in lines:
                    lines.append(s)
            for line in lines[:20]:
                print("HIT:", line)
        except Exception as e:
            print("ERR:", repr(e))
    browser.close()
