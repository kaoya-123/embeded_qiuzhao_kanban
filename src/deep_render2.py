from pathlib import Path
from playwright.sync_api import sync_playwright

K="嵌入式|BSP|驱动|RTOS|Linux|MCU|单片机|车载|软件工程师|硬件工程师|校招|2027|27届|校园|秋招|正式批|岗位|职位|工程师"
pages2 = {
    "OPPO_jobs":"https://careers.oppo.com/university/oppo/campus/jobs",
    "小米_list":"https://app.mokahr.com/campus-recruitment/xiaomi/44871#/jobs",
}
OUT=Path(__file__).parents[1]/"data"/"job_pages2"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    pg=b.new_page(viewport={"width":1440,"height":1200})
    for n,u in pages2.items():
        pg.goto(u, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(15000)
        # try click buttons
        for t in ["校园招聘","全部","在招","职位","岗位"]:
            try:
                l=pg.get_by_text(t,exact=False).first
                if l.count(): l.click(timeout=2000); pg.wait_for_timeout(4000)
            except: pass
        txt=pg.locator("body").inner_text(timeout=20000)
        (OUT/f"{n}.txt").write_text("TITLE:"+pg.title()+"\nURL:"+pg.url+"\n\n"+txt, encoding="utf-8")
        print(n, len(txt), pg.url)
    b.close()
