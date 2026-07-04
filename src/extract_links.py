from pathlib import Path
from playwright.sync_api import sync_playwright

URLS = {
    "dji": "https://careers.dji.com/zh-CN/campus",
    "oppo": "https://careers.oppo.com/campus",
    "vivo": "https://hr.vivo.com/wt/vivo/web/index/campus",
    "inovance": "https://inovance.zhiye.com/",
    "huawei": "https://career.huawei.com/reccampportal/portal5/index.html",
}
OUT = Path(__file__).resolve().parents[1] / "data" / "links"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    for name, url in URLS.items():
        lines = []
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)
            lines.append(f"TITLE: {page.title()}")
            lines.append(f"URL: {page.url}")
            lines.append("\n--- LINKS ---")
            links = page.locator("a").evaluate_all("els => els.map(a => ({text:(a.innerText||a.textContent||'').trim(), href:a.href})).filter(x => x.text || x.href)")
            seen = set()
            for x in links:
                key = (x.get('text',''), x.get('href',''))
                if key in seen:
                    continue
                seen.add(key)
                text = (x.get('text') or '').replace('\n',' / ')
                href = x.get('href') or ''
                if any(k in text+href for k in ['岗位','职位','投递','校招','校园','job','position','career','campus','申请','启程','在招']):
                    lines.append(f"TEXT: {text}\nHREF: {href}\n")
            lines.append("\n--- BUTTONS ---")
            buttons = page.locator("button").evaluate_all("els => els.map(b => (b.innerText||b.textContent||'').trim()).filter(Boolean)")
            for b in buttons:
                if any(k in b for k in ['岗位','职位','投递','查看','启程','在招','校招','申请']):
                    lines.append(f"BUTTON: {b}")
        except Exception as e:
            lines.append("ERR: " + repr(e))
        (OUT / f"{name}_links.txt").write_text("\n".join(lines), encoding="utf-8")
    browser.close()
