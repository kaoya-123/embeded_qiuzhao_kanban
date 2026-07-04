"""
BOSS直聘搜索 — 带人机交互：弹浏览器 → 用户登录 → 用户说「好了」→ 搜
完全模仿小红书 cdp_publish 的交互模式
"""
import json, time, sys, os, re, subprocess
from urllib.parse import quote

# 确保 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_PORT = 9223
SIGNAL_FILE = os.path.join(os.path.dirname(__file__), "boss_signal.txt")
OUTFILE = os.path.join(os.path.dirname(__file__), "boss_search_results.json")

def find_chrome():
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.isfile(p): return p
    return None

def cdp_request(path, method="GET", body=None):
    url = f"http://127.0.0.1:{CDP_PORT}{path}"
    if method == "GET":
        return requests.get(url, timeout=5).json()
    else:
        return requests.put(url, json=body, timeout=5).json()

def main():
    import requests
    import websockets.sync.client as ws_client

    # 清理信号
    if os.path.exists(SIGNAL_FILE):
        os.remove(SIGNAL_FILE)

    # 启动 Chrome CDP
    chrome = find_chrome()
    if not chrome:
        print("未找到 Chrome")
        return

    ud = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")

    print("正在启动 Chrome 浏览器...")
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={ud}",
        "--no-first-run", "--no-default-browser-check",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等 CDP 就绪
    for i in range(20):
        time.sleep(1.5)
        try:
            r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
            if r.status_code == 200:
                break
        except:
            pass
    else:
        print("Chrome CDP 启动超时")
        return

    # 打开 BOSS 直聘
    requests.put(f"http://127.0.0.1:{CDP_PORT}/json/new?https://www.zhipin.com/", timeout=5)

    print("\n" + "=" * 50)
    print("Chrome 浏览器已打开，请登录 BOSS 直聘")
    print("登录完成后在对话里告诉我「好了」")
    print("=" * 50)

    # 等信号
    while True:
        time.sleep(2)
        if os.path.exists(SIGNAL_FILE):
            with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
                if f.read().strip() == "go":
                    with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
                        f.write("consumed")
                    break

    # 连上 WebSocket 开始搜索
    resp = requests.get(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5)
    pages = [t for t in resp.json() if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
    if not pages:
        print("获取不到 CDP tab")
        return
    ws_url = pages[0]["webSocketDebuggerUrl"]

    ws = ws_client.connect(ws_url)

    # CDP helper
    def cmd(method, params=None):
        mid = int(time.time() * 100000) % 1000000
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        buf, dl = b"", time.time() + 30
        while time.time() < dl:
            try:
                chunk = ws.recv(timeout=5)
                if isinstance(chunk, str): chunk = chunk.encode("utf-8")
                buf += chunk
                try:
                    m = json.loads(buf.decode("utf-8", errors="replace"))
                    if m.get("id") == mid:
                        return m.get("result", {})
                except json.JSONDecodeError:
                    pass
            except:
                pass
        return {}

    def ev(expr):
        return cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True}).get("result", {}).get("value")

    print("\n开始搜索...")

    keywords = [
        "2027届 嵌入式 校招",
        "2027届 嵌入式软件 应届生",
        "2027届 BSP RTOS 校招",
        "2027届 MCU 单片机 校招",
        "2027届 驱动开发 Linux 校招",
        "2027届 嵌入式 Linux 校招",
    ]

    results, seen = [], set()

    for kw in keywords:
        url = f"https://www.zhipin.com/web/geek/job?query={quote(kw)}&city=100010000"
        cmd("Page.navigate", {"url": url})
        time.sleep(6)

        # scroll
        for _ in range(5):
            ev("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)

        raw = ev("""(function(){
            var out=[];
            document.querySelectorAll('.job-card-wrap,[class*="job-card"],.job-primary,.search-job-result li,[class*="job-list"]>div,[class*="job-item"]').forEach(function(c){
                out.push({
                    text:(c.innerText||c.textContent||'').substring(0,500),
                    href:(c.querySelector('a[href*="/job_detail/"]')||{}).href||''
                });
            });
            return JSON.stringify(out);
        })()""")

        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except:
            continue

        for item in items:
            text = item.get("text", "")
            if not any(t in text for t in ['嵌入式','BSP','驱动','RTOS','MCU','单片机','底层','Linux']):
                continue
            if '2027' not in text and '应届' not in text:
                continue
            if any(t in text for t in ['实习生','实习转正','暑期实习','校储实习']):
                continue

            company = job = salary = loc = ""
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                if re.search(r'\d+[kK千]', line) and not salary: salary = line
                elif any(c in line for c in ['北京','上海','深圳','杭州','广州','成都','武汉','西安','南京','苏州']):
                    if not loc: loc = line
                elif not job and len(line) > 2:
                    job = line
                elif job and not company and len(line) > 1:
                    company = line

            key = f"{company}|{job}"
            if key in seen or not company: continue
            seen.add(key)
            results.append({"company":company,"job":job,"salary":salary,"location":loc,"boss_link":item.get("href"),"source":kw})

    ws.close()

    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # summary
    with open(os.path.join(os.path.dirname(__file__), "boss_summary.txt"), "w", encoding="utf-8") as f:
        f.write(f"Total: {len(results)}\n\n")
        for r in results:
            f.write(f"{r['company']} | {r['job'][:60]} | {r['location']} | {r['salary']}\n")

    print(f"\n完成！去重后 {len(results)} 家公司")
    print(f"详细结果: {OUTFILE}")

if __name__ == "__main__":
    main()
