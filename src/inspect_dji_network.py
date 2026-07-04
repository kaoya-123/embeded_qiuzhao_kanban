from pathlib import Path
from playwright.sync_api import sync_playwright
import json

OUT = Path(__file__).resolve().parents[1] / "data" / "dji_network"
OUT.mkdir(parents=True, exist_ok=True)
url = "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    logs=[]
    def on_response(resp):
        u=resp.url
        if any(k in u.lower() for k in ["job", "position", "recruit", "campus", "api", "graphql", "list"]):
            try:
                ct=resp.headers.get('content-type','')
                if 'json' in ct or 'text' in ct:
                    body=resp.text()[:20000]
                    logs.append({"url":u,"status":resp.status,"ct":ct,"body":body})
            except Exception:
                pass
    page.on("response", on_response)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    # 尝试点职位列表/返回/搜索
    for label in ["职位列表", "校招职位", "全部职位", "查看在招职位", "返回"]:
        try:
            loc=page.get_by_text(label, exact=False).first
            if loc.count():
                loc.click(timeout=1500)
                page.wait_for_timeout(5000)
        except Exception:
            pass
    text=page.locator("body").inner_text(timeout=20000)
    (OUT/"body.txt").write_text(text, encoding="utf-8")
    (OUT/"responses.json").write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    print("responses", len(logs), "url", page.url, "text", len(text))
    browser.close()
