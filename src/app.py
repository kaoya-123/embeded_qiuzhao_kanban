"""
嵌入式秋招雷达 - 全自动服务
启动后自动：
  1. 立即扫描一次已开放公司/岗位 → 写入机会发现池
  2. 每隔 N 小时重新扫描
  3. 提供网页看板，自动刷新
"""
import os, re, json, threading, time, argparse
from datetime import datetime, timedelta
from collections import Counter

import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from dedupe_utils import (
    choose_best_pool_record,
    discovery_cluster_key,
    discovery_exact_key,
    extract_url_value,
    is_description_like_job,
    merge_pool_fields,
    normalize_job_name,
)

try:
    from dynamic_scan_jobs import scan_dynamic
except Exception:
    scan_dynamic = None

try:
    from sync_pool_to_main import sync_pool_to_main
except Exception:
    sync_pool_to_main = lambda: 0

try:
    from audit_pool import audit_and_dedup
except Exception:
    audit_and_dedup = lambda: 0

def dedup_pool():
    """机会池语义去重：同公司同来源同开放类型只保留质量最高的一条。"""
    try:
        pool_recs = list_records(DISCOVERY_TABLE_ID)
        from collections import defaultdict
        groups = defaultdict(list)
        for r in pool_recs:
            groups[discovery_cluster_key(r.get("fields", {}))].append(r)
        to_delete = []
        for key, recs in groups.items():
            if len(recs) > 1:
                keeper = choose_best_pool_record(recs)
                for r in recs:
                    if r["record_id"] != keeper["record_id"]:
                        to_delete.append(r["record_id"])
        if to_delete:
            _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records/batch_delete",
                    method="POST", payload={"records": to_delete})
            print(f"[去重] 删除了 {len(to_delete)} 条重复机会记录")
    except Exception as e:
        print(f"[去重异常] {e}")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"

CAMPUS_RE = re.compile(r"2027届|2027|27届|2026.{0,10}校园招聘|校园招聘|校招|提前批", re.I)
JOB_RE = re.compile(r"[^，。；;\n\r<>]{0,20}(嵌入式|BSP|驱动|RTOS|Linux|MCU|单片机|车载|底层软件)[^，。；;\n\r<>]{0,30}(工程师|开发|岗位|职位)", re.I)
EMBEDDED_RE = re.compile(r"嵌入式|embedded|BSP|驱动|RTOS|FreeRTOS|Linux|MCU|单片机|车载|底层软件|硬件", re.I)

# ------- 飞书 API 封装 -------
def _token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0: raise RuntimeError(d)
    return d["tenant_access_token"]

def _feishu(path, method="GET", payload=None):
    h = {"Authorization": f"Bearer {_token()}"}
    if method == "GET":
        r = requests.get(f"{API}{path}", headers=h, params=payload or {}, timeout=30)
    else:
        r = requests.post(f"{API}{path}", headers=h, json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0: raise RuntimeError(d)
    return d.get("data", {})

def list_records(table_id):
    recs, pt = [], None
    while True:
        p = {"page_size": 500}
        if pt: p["page_token"] = pt
        data = _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records", payload=p)
        recs.extend(data.get("items", []))
        if not data.get("has_more"): return recs
        pt = data.get("page_token")

def batch_create(table_id, records):
    return _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
                   method="POST", payload={"records": records})

# ------- 扫描引擎 -------
def _url_val(v):
    return extract_url_value(v)

def _clean(html):
    for tag in ("script","style"): html = re.sub(f"<{tag}[\\s\\S]*?</{tag}>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()

def _dedupe(company, url, dtype, job):
    return discovery_exact_key(company, url, dtype, job)

def _infer_direction(text):
    m = []
    if re.search(r"BSP|驱动|driver|内核", text, re.I): m += ["Linux驱动","BSP"]
    if re.search(r"RTOS|FreeRTOS|实时", text, re.I): m.append("RTOS")
    if re.search(r"MCU|单片机|STM32", text, re.I): m.append("MCU裸机")
    if re.search(r"车载|汽车|座舱|智驾", text, re.I): m.append("车载嵌入式")
    if re.search(r"Linux|应用|终端", text, re.I): m.append("Linux应用")
    return list(dict.fromkeys(m)) or ["其他"]

scan_log = []
scan_lock = threading.Lock()

def do_scan():
    """执行一次全量扫描，返回 (检查数, 新增数, 新增标题列表)"""
    t0 = time.time()
    try:
        main_recs = list_records(MAIN_TABLE_ID)
        pool_recs = list_records(DISCOVERY_TABLE_ID)
        seen = {r.get("fields",{}).get("去重Key") for r in pool_recs if r.get("fields",{}).get("去重Key")}
        today_ms = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

        candidates, created = [], []
        for r in main_recs:
            f = r.get("fields", {})
            co = f.get("公司名称")
            if not co: continue
            url = _url_val(f.get("招聘入口")) or _url_val(f.get("官网")) or _url_val(f.get("投递链接"))
            if not url or not url.startswith("http"): continue
            candidates.append((co, url))

        for co, url in candidates:
            try:
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
                                   timeout=15, allow_redirects=True)
                txt = _clean(resp.text[:200000])
            except:
                continue
            if not CAMPUS_RE.search(txt): continue
            job_m = JOB_RE.search(txt)
            has_em = bool(EMBEDDED_RE.search(txt))
            if job_m and has_em:
                candidate_job = normalize_job_name(job_m.group(0)[:100])
                if is_description_like_job(candidate_job):
                    dtype, jname = "公司校招开放", "待确认具体岗位"
                    dirs, conf, status = [], ("高" if "2027" in txt or "27届" in txt else "中"), "疑似开放"
                else:
                    dtype, jname = "嵌入式岗位开放", candidate_job
                    dirs = _infer_direction(jname + " " + txt[:5000])
                    conf = "高"
                    status = "已开放"
            else:
                dtype, jname = "公司校招开放", "待确认具体岗位"
                dirs, conf = [], ("高" if "2027" in txt or "27届" in txt else "中")
                status = "疑似开放"
            key = _dedupe(co, resp.url, dtype, jname)
            if key in seen: continue
            title = f"{co}：{dtype}"
            if jname != "待确认具体岗位": title += f" - {jname}"
            flds = {
                "标题": title, "疑似公司": co, "疑似嵌入式方向": dirs or [],
                "来源平台": "官网", "来源链接": {"link": resp.url, "text": resp.url},
                "投递链接": {"link": resp.url, "text": resp.url},
                "命中关键词": ",".join(sorted(set(CAMPUS_RE.findall(txt)[:10]))),
                "发现时间": today_ms, "首次发现时间": today_ms, "最近检测时间": today_ms,
                "可信度": conf, "处理状态": "待确认", "岗位开放状态": status,
                "岗位名称": jname,
                "JD原文": txt[:1500] if dtype == "嵌入式岗位开放" else "已检测到校招开放；具体嵌入式岗位需进入来源确认。",
                "发现类型": dtype, "是否新增": True, "去重Key": key,
            }
            created.append({"fields": flds})
            seen.add(key)

        if created:
            batch_create(DISCOVERY_TABLE_ID, created)
        dynamic_created = []
        if scan_dynamic:
            try:
                dynamic_created = scan_dynamic()
            except Exception as dyn_error:
                # 动态抓取失败不影响公司级扫描
                dynamic_created = []
                print(f"[动态岗位扫描异常] {dyn_error}")
        elapsed = round(time.time() - t0, 1)
        total_created = len(created) + len(dynamic_created)
        titles = [r["fields"]["标题"] for r in created] + [r["fields"]["标题"] for r in dynamic_created]
        result = {"checked": len(candidates), "created": total_created, "titles": titles, "elapsed": elapsed}

        # 自动补齐：机会池新公司若主表没有，新增到主表
        try:
            sync_new = sync_pool_to_main()
            if sync_new:
                result["synced_new"] = sync_new
        except Exception as sync_error:
            result["sync_error"] = str(sync_error)

        # 每次扫描后自动去重+审计
        try:
            audit_and_dedup()
        except Exception:
            pass

        # 去重：机会发现池自动去重，避免同一公司同一岗位重复
        try:
            dedup_pool()
        except Exception:
            pass
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        result = {"checked": 0, "created": 0, "titles": [], "elapsed": elapsed, "error": str(e)}
    with scan_lock:
        scan_log.append({"time": datetime.now().strftime("%H:%M:%S"), **result})
        if len(scan_log) > 50: scan_log.pop(0)
    return result

# ------- 数据读取（给看板用） -------
def get_main_stats():
    recs = list_records(MAIN_TABLE_ID)
    rows = [r["fields"] for r in recs if r.get("fields",{}).get("公司名称")]
    progress, directions, ctypes = Counter(), Counter(), Counter()
    exam_counter, interview_counter, offer_counter = Counter(), Counter(), Counter()
    for f in rows:
        for p in f.get("进展", []) or []: progress[p] += 1
        # 单独统计机考/面试/OC
        has_exam = f.get("机考时间") and f.get("机考时间") != 0
        has_interview = f.get("一面") or f.get("二面") or f.get("三面")
        has_offer = any(oc in (f.get("进展") or []) for oc in ["OC", "OC"])
        if has_exam: exam_counter["机考"] += 1
        if has_interview: interview_counter["面试中"] += 1
        if has_offer: offer_counter["Offer"] += 1
        for d in f.get("嵌入式方向", []) or []: directions[d] += 1
        for c in f.get("公司/行业类型", []) or []: ctypes[c] += 1
    total_p0 = sum(1 for f in rows if f.get("意愿") == "P0-高意愿")
    # 你的投递记录：投递时间不为空的=已投递，只展示已投递公司
    recent = [
        r for r in rows
        if r.get("投递时间") and r.get("投递时间") != 0
    ]
    # 按投递时间倒序
    recent.sort(key=lambda f: f.get("投递时间", 0) or 0, reverse=True)
    return {
        "total_companies": len(rows),
        "total_progress": sum(progress.values()),
        "p0_count": total_p0,
        "progress": progress.most_common(15),
        "exam_count": sum(exam_counter.values()),
        "interview_count": sum(interview_counter.values()),
        "offer_count": sum(offer_counter.values()),
        "directions": directions.most_common(15),
        "ctypes": ctypes.most_common(15),
        "recent": [
            {"company": f.get("公司名称",""), "type": (f.get("公司/行业类型") or [])[0] if f.get("公司/行业类型") else "",
             "dir": f.get("嵌入式方向", []), "progress": f.get("进展", []),
             "job": f.get("秋招岗位",""),
             "url": _url_val(f.get("投递链接")),
             "deadline": f.get("投递截止时间", 0),
             "apply_date": f.get("投递时间", ""),
             "exam_date": f.get("机考时间", ""),
             "interview1": f.get("一面", ""),
             "interview2": f.get("二面", "")}
            for f in recent
        ]
    }

def get_pool_stats():
    recs = list_records(DISCOVERY_TABLE_ID)
    rows = [r["fields"] for r in recs]
    return {
        "total": len(rows),
        "rows": [
            {"title": f.get("标题",""), "company": f.get("疑似公司",""),
             "job": f.get("岗位名称",""), "dir": f.get("疑似嵌入式方向", []),
             "status": f.get("岗位开放状态",""), "type": f.get("发现类型",""),
             "url": _url_val(f.get("来源链接")), "conf": f.get("可信度",""),
             "deadline": f.get("投递截至时间", ""),
             "location": f.get("工作地点", [])}
            for f in rows[-50:]
        ]
    }

def get_scan_log():
    with scan_lock:
        return list(scan_log)

# ------- Flask 应用 -------
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    with open(os.path.join(os.path.dirname(__file__), "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()

@flask_app.route("/data")
def data():
    return {
        "main": get_main_stats(),
        "pool": get_pool_stats(),
        "scan_log": get_scan_log(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

@flask_app.route("/scan", methods=["POST"])
def trigger_scan():
    """手动触发一次全量扫描并同步"""
    try:
        result = do_scan()
        # auto-sync after scan
        try:
            synced = sync_pool_to_main()
            result["synced"] = synced
        except Exception as e:
            result["sync_error"] = str(e)
        return {
            "success": True,
            "checked": result.get("checked", 0),
            "created": result.get("created", 0),
            "synced": result.get("synced", 0),
            "elapsed": result.get("elapsed", 0),
            "titles": result.get("titles", []),
            "error": result.get("error", ""),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}



# ------- 启动入口 -------
def start(initial_scan=True):
    print("=== 嵌入式秋招雷达 启动 ===")
    print(f"看板地址: http://localhost:8765")
    print(f"定时扫描: 每4小时一次" + ("（立即执行首次扫描）" if initial_scan else "（已跳过首次扫描）"))
    print()

    if initial_scan:
        print("[首次扫描] 开始...")
        r = do_scan()
        print(f"  检查 {r['checked']} 条，新增 {r['created']} 条")
    else:
        print("[首次扫描] 已跳过，仅启动看板")

    # 定时任务
    sched = BackgroundScheduler()
    sched.add_job(lambda: (print(f"[定时扫描 {datetime.now():%H:%M}] 完成，新增 {do_scan().get('created',0)} 条"),), 'interval', hours=4, id='scan_job')
    sched.start()

    flask_app.run(host="0.0.0.0", port=8765, debug=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="嵌入式秋招雷达看板服务")
    parser.add_argument("--no-initial-scan", action="store_true", help="启动看板时跳过首次扫描，适合只预览 UI")
    args = parser.parse_args()
    start(initial_scan=not args.no_initial_scan)
