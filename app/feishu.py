"""飞书 API 封装 + 扫描引擎 + 看板数据读取。

从原 src/app.py 抽出，去掉 Flask 依赖，改用 bus.log 报进度、state 存状态。
业务逻辑（去重/同步/审计/动态抓取）仍复用 src/ 下脚本。
"""
import os
import re
import sys
import time
import threading
from datetime import datetime
from collections import Counter

import requests
from dotenv import load_dotenv

# 复用 src/ 下的业务逻辑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dedupe_utils import (  # noqa: E402
    choose_best_pool_record,
    discovery_cluster_key,
    discovery_exact_key,
    extract_url_value,
    is_description_like_job,
    normalize_job_name,
)

from app import bus  # noqa: E402

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

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
CONFIG_KEYS = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "MAIN_TABLE_ID", "DISCOVERY_TABLE_ID"]
REQUIRED_CONFIG_KEYS = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "MAIN_TABLE_ID"]

load_dotenv(ENV_PATH)

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"


def _apply_config(cfg: dict) -> None:
    global APP_ID, APP_SECRET, APP_TOKEN, MAIN_TABLE_ID, DISCOVERY_TABLE_ID
    APP_ID = cfg.get("FEISHU_APP_ID") or ""
    APP_SECRET = cfg.get("FEISHU_APP_SECRET") or ""
    APP_TOKEN = cfg.get("FEISHU_APP_TOKEN") or ""
    MAIN_TABLE_ID = cfg.get("MAIN_TABLE_ID") or ""
    DISCOVERY_TABLE_ID = cfg.get("DISCOVERY_TABLE_ID") or ""


def get_config() -> dict:
    names = {
        "FEISHU_APP_ID": "APP_ID",
        "FEISHU_APP_SECRET": "APP_SECRET",
        "FEISHU_APP_TOKEN": "APP_TOKEN",
        "MAIN_TABLE_ID": "MAIN_TABLE_ID",
        "DISCOVERY_TABLE_ID": "DISCOVERY_TABLE_ID",
    }
    return {k: globals().get(names[k]) or os.getenv(k) or "" for k in CONFIG_KEYS}


def save_config(cfg: dict) -> None:
    """保存飞书配置到 .env，并立即更新当前进程内配置。"""
    merged = get_config()
    merged.update({k: (cfg.get(k) or "").strip() for k in CONFIG_KEYS})
    old_lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            old_lines = f.read().splitlines()
    seen, out = set(), []
    for line in old_lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in CONFIG_KEYS:
            out.append(f"{key}={merged[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key in CONFIG_KEYS:
        if key not in seen:
            out.append(f"{key}={merged[key]}")
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out).strip() + "\n")
    os.environ.update(merged)
    _apply_config(merged)


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if any(k in text for k in ("SSLError", "ConnectionError", "10054", "Max retries", "EOF", "timed out", "Timeout")):
        return "连不上飞书 open.feishu.cn：请检查网络出口、代理或 IP 白名单。"
    if "99991663" in text or "tenant_access_token" in text:
        return "飞书 App ID / App Secret 可能不正确，或应用尚未发布。"
    if "1254003" in text or "table" in text.lower() or "bitable" in text.lower():
        return "飞书多维表格 App Token 或 Table ID 可能不正确，或应用没有该表权限。"
    return f"飞书连接失败：{text[:220]}"


def test_config(cfg: dict) -> bool:
    old = get_config()
    _apply_config({k: (cfg.get(k) or "").strip() for k in CONFIG_KEYS})
    try:
        cfg_now = get_config()
        missing = [k for k in REQUIRED_CONFIG_KEYS if not cfg_now.get(k)]
        if missing:
            raise RuntimeError("缺少配置：" + ", ".join(missing))
        # 读取 1 条主表记录，确认 token/table/权限可用。机会发现池已废弃，DISCOVERY_TABLE_ID 可选。
        _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN_TABLE_ID}/records", payload={"page_size": 1})
        if DISCOVERY_TABLE_ID:
            _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records", payload={"page_size": 1})
        return True
    finally:
        _apply_config(old)

CAMPUS_RE = re.compile(r"2027届|2027|27届|2026.{0,10}校园招聘|校园招聘|校招|提前批", re.I)
JOB_RE = re.compile(r"[^，。；;\n\r<>]{0,20}(嵌入式|BSP|驱动|RTOS|Linux|MCU|单片机|车载|底层软件)[^，。；;\n\r<>]{0,30}(工程师|开发|岗位|职位)", re.I)
EMBEDDED_RE = re.compile(r"嵌入式|embedded|BSP|驱动|RTOS|FreeRTOS|Linux|MCU|单片机|车载|底层软件|硬件", re.I)


# ------- 飞书 API 封装 -------
def _token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d["tenant_access_token"]


def _feishu(path, method="GET", payload=None):
    h = {"Authorization": f"Bearer {_token()}"}
    if method == "GET":
        r = requests.get(f"{API}{path}", headers=h, params=payload or {}, timeout=30)
    else:
        r = requests.post(f"{API}{path}", headers=h, json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d.get("data", {})


def list_records(table_id):
    recs, pt = [], None
    while True:
        p = {"page_size": 500}
        if pt:
            p["page_token"] = pt
        data = _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records", payload=p)
        recs.extend(data.get("items", []))
        if not data.get("has_more"):
            return recs
        pt = data.get("page_token")


def list_fields(table_id):
    data = _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields", payload={"page_size": 200})
    out = {}
    for item in data.get("items", []):
        name = item.get("field_name")
        if name:
            out[name] = item
    return out


def batch_update(table_id, records):
    total = 0
    for i in range(0, len(records or []), 500):
        batch = records[i:i + 500]
        if batch:
            _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_update",
                    method="POST", payload={"records": batch})
            total += len(batch)
    return total


def batch_create(table_id, records):
    return _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create",
                   method="POST", payload={"records": records})


def batch_delete(table_id, record_ids):
    return _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_delete",
                   method="POST", payload={"records": record_ids})


def existing_discovery_keys():
    """读取机会发现池已有去重 Key，用于检索预览/写入前去重。"""
    keys = set()
    for r in list_records(DISCOVERY_TABLE_ID):
        k = r.get("fields", {}).get("去重Key")
        if k:
            keys.add(k)
    return keys


def create_discovery_records(records):
    """批量写入机会发现池，返回创建数量。"""
    total = 0
    for i in range(0, len(records or []), 500):
        batch = records[i:i + 500]
        if batch:
            batch_create(DISCOVERY_TABLE_ID, batch)
            total += len(batch)
    return total


# ------- 扫描引擎 -------
def _url_val(v):
    return extract_url_value(v)


def clean_html(html):
    for tag in ("script", "style"):
        html = re.sub(f"<{tag}[\\s\\S]*?</{tag}>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


# 向后兼容：原代码用 _clean
_clean = clean_html


def _infer_direction(text):
    m = []
    if re.search(r"BSP|驱动|driver|内核", text, re.I):
        m += ["Linux驱动", "BSP"]
    if re.search(r"RTOS|FreeRTOS|实时", text, re.I):
        m.append("RTOS")
    if re.search(r"MCU|单片机|STM32", text, re.I):
        m.append("MCU裸机")
    if re.search(r"车载|汽车|座舱|智驾", text, re.I):
        m.append("车载嵌入式")
    if re.search(r"Linux|应用|终端", text, re.I):
        m.append("Linux应用")
    return list(dict.fromkeys(m)) or ["其他"]


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
            batch_delete(DISCOVERY_TABLE_ID, to_delete)
            bus.log(f"去重：删除了 {len(to_delete)} 条重复机会记录", channel="scan")
    except Exception as e:
        bus.log(f"去重异常：{e}", channel="scan", level="error")


def do_scan():
    """执行一次全量扫描，返回结果摘要，并通过 bus.log 报进度。"""
    t0 = time.time()
    bus.log("开始扫描主表公司官网…", channel="scan")
    try:
        main_recs = list_records(MAIN_TABLE_ID)
        pool_recs = list_records(DISCOVERY_TABLE_ID)
        seen = {r.get("fields", {}).get("去重Key") for r in pool_recs if r.get("fields", {}).get("去重Key")}
        today_ms = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

        candidates, created = [], []
        for r in main_recs:
            f = r.get("fields", {})
            co = f.get("公司名称")
            if not co:
                continue
            url = _url_val(f.get("招聘入口")) or _url_val(f.get("官网")) or _url_val(f.get("投递链接"))
            if not url or not url.startswith("http"):
                continue
            candidates.append((co, url))

        bus.log(f"共 {len(candidates)} 家公司待检测", channel="scan")
        for idx, (co, url) in enumerate(candidates, 1):
            try:
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
                                    timeout=15, allow_redirects=True)
                txt = _clean(resp.text[:200000])
            except Exception:
                continue
            if not CAMPUS_RE.search(txt):
                continue
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
            key = discovery_exact_key(co, resp.url, dtype, jname)
            if key in seen:
                continue
            title = f"{co}：{dtype}"
            if jname != "待确认具体岗位":
                title += f" - {jname}"
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
            bus.log(f"[{idx}/{len(candidates)}] {co} → {title}", channel="scan")

        if created:
            batch_create(DISCOVERY_TABLE_ID, created)

        dynamic_created = []
        if scan_dynamic:
            try:
                bus.log("动态渲染抓取岗位…", channel="scan")
                dynamic_created = scan_dynamic()
            except Exception as dyn_error:
                dynamic_created = []
                bus.log(f"动态岗位扫描异常：{dyn_error}", channel="scan", level="error")

        elapsed = round(time.time() - t0, 1)
        total_created = len(created) + len(dynamic_created)
        titles = [r["fields"]["标题"] for r in created] + [r["fields"]["标题"] for r in dynamic_created]
        result = {"checked": len(candidates), "created": total_created, "titles": titles, "elapsed": elapsed, "time": datetime.now().strftime("%H:%M:%S")}

        try:
            sync_new = sync_pool_to_main()
            if sync_new:
                result["synced_new"] = sync_new
                bus.log(f"自动补齐主表新增 {sync_new} 条", channel="scan")
        except Exception as sync_error:
            result["sync_error"] = str(sync_error)

        try:
            audit_and_dedup()
        except Exception:
            pass

        try:
            dedup_pool()
        except Exception:
            pass

        bus.log(f"扫描完成：检查 {result['checked']} 条，新增 {total_created} 条，用时 {elapsed}s", channel="scan", level="success")
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        result = {"checked": 0, "created": 0, "titles": [], "elapsed": elapsed, "error": str(e), "time": datetime.now().strftime("%H:%M:%S")}
        bus.log(f"扫描失败：{e}", channel="scan", level="error")
    return result


# ------- 数据读取（给看板用） -------
def get_main_stats():
    recs = list_records(MAIN_TABLE_ID)
    rows = [r["fields"] for r in recs if r.get("fields", {}).get("公司名称")]
    progress, directions, ctypes = Counter(), Counter(), Counter()
    exam_counter, interview_counter, offer_counter = Counter(), Counter(), Counter()
    for f in rows:
        for p in f.get("进展", []) or []:
            progress[p] += 1
        has_exam = f.get("机考时间") and f.get("机考时间") != 0
        has_interview = f.get("一面") or f.get("二面") or f.get("三面")
        has_offer = any(oc in (f.get("进展") or []) for oc in ["OC"])
        if has_exam:
            exam_counter["机考"] += 1
        if has_interview:
            interview_counter["面试中"] += 1
        if has_offer:
            offer_counter["Offer"] += 1
        for d in f.get("嵌入式方向", []) or []:
            directions[d] += 1
        for c in f.get("公司/行业类型", []) or []:
            ctypes[c] += 1
    total_p0 = sum(1 for f in rows if f.get("意愿") == "P0-高意愿")
    recent = [r for r in rows if r.get("投递时间") and r.get("投递时间") != 0]
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
            {"company": f.get("公司名称", ""), "type": (f.get("公司/行业类型") or [""])[0] if f.get("公司/行业类型") else "",
             "dir": f.get("嵌入式方向", []), "progress": f.get("进展", []),
             "job": f.get("秋招岗位", ""),
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
    # 机会发现池已从当前产品主流程中移除；看板和主表补齐不再依赖它。
    # 保持返回结构，避免旧前端字段访问报错。
    return {"total": 0, "rows": []}


def get_dashboard_data():
    return {
        "main": get_main_stats(),
        "pool": get_pool_stats(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
