from pathlib import Path
from playwright.sync_api import sync_playwright

TEST = {
    "小米":"https://xiaomi.jobs.feishu.cn/campus/",
    "OPPO_岗位":"https://careers.oppo.com/university/oppo/campus?category=all",
    "海康_岗位":"https://wecruit.hotjob.cn/SU5e1e0c02f77d71d84b35ccb0/pb/school.html?orgCode=0%2F5&currentPage=1",
}
OUT=Path(__file__).parents[1]/"data"/"job_pages3"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    pg=b.new_page(viewport={"width":1440,"height":1200})
    for name,url in TEST.items():
        print(name,url)
        try:
            pg.goto(url,wait_until="domcontentloaded",timeout=60000)
            pg.wait_for_timeout(15000)
            for t in ["校园","全部","在招","职位","岗位"]:
                try:
                    l=pg.get_by_text(t,exact=False).first
                    if l.count(): l.click(timeout=2000); pg.wait_for_timeout(4000)
                except: pass
            txt=pg.locator("body").inner_text(timeout=20000)
            (OUT/f"{name}.txt").write_text("TITLE:"+pg.title()+"\nURL:"+pg.url+"\n\n"+txt, encoding="utf-8")
            print("ok",len(txt))
        except Exception as e:
            (OUT/f"{name}.txt").write_text("ERR:"+repr(e), encoding="utf-8")
            print("err",e)
    b.close()
