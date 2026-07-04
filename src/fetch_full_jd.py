from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "data" / "full_jd"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = {
    "大疆嵌入式": "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/job/c688765c-8541-42a6-9edf-fb23849e65fc",
    "拓竹嵌入式": "https://careers.bambulab.com/campus",
    "禾赛BSP": "https://careers.hesaitech.com/",
}

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width":1440,"height":1200})
    for name, url in PAGES.items():
        print(f"  {name} ...")
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(12000)
            text = pg.locator("body").inner_text(timeout=20000)
            final_url = pg.url
            (OUT / f"{name}.txt").write_text(
                "FINAL_URL: " + final_url + "\nTITLE: " + pg.title() + "\n\n" + text,
                encoding="utf-8"
            )
            print(f"    ok {len(text)} chars -> {final_url}")
        except Exception as e:
            (OUT / f"{name}.txt").write_text("ERR: " + repr(e), encoding="utf-8")
            print(f"    err {repr(e)}")
    b.close()
print("done")
