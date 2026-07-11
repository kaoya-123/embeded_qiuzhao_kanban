"""飞书 API 封装 + 看板数据读取。"""
import os
from datetime import datetime
from collections import Counter

import requests
from dotenv import load_dotenv

from app import bus  # noqa: E402

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
CONFIG_KEYS = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_APP_TOKEN",
    "MAIN_TABLE_ID",
]
REQUIRED_CONFIG_KEYS = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "MAIN_TABLE_ID"]

load_dotenv(ENV_PATH)

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
API = "https://open.feishu.cn/open-apis"


def _apply_config(cfg: dict) -> None:
    global APP_ID, APP_SECRET, APP_TOKEN, MAIN_TABLE_ID
    APP_ID = cfg.get("FEISHU_APP_ID") or ""
    APP_SECRET = cfg.get("FEISHU_APP_SECRET") or ""
    APP_TOKEN = cfg.get("FEISHU_APP_TOKEN") or ""
    MAIN_TABLE_ID = cfg.get("MAIN_TABLE_ID") or ""


def get_config() -> dict:
    names = {
        "FEISHU_APP_ID": "APP_ID",
        "FEISHU_APP_SECRET": "APP_SECRET",
        "FEISHU_APP_TOKEN": "APP_TOKEN",
        "MAIN_TABLE_ID": "MAIN_TABLE_ID",
    }
    return {k: (globals().get(names[k]) if k in names else None) or os.getenv(k) or "" for k in CONFIG_KEYS}


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
        _feishu(f"/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN_TABLE_ID}/records", payload={"page_size": 1})
        return True
    finally:
        _apply_config(old)


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
    recent = [r for r in rows if r.get("投递时间") and r.get("投递时间") != 0]
    recent.sort(key=lambda f: f.get("投递时间", 0) or 0, reverse=True)
    return {
        "total_companies": len(rows),
        "exam_count": sum(exam_counter.values()),
        "interview_count": sum(interview_counter.values()),
        "offer_count": sum(offer_counter.values()),
        "directions": directions.most_common(15),
        "ctypes": ctypes.most_common(15),
        "recent": [
            {"company": f.get("公司名称", ""),
             "type": (f.get("公司/行业类型") or [""])[0] if f.get("公司/行业类型") else "",
             "dir": f.get("嵌入式方向", []),
             "progress": f.get("进展", []),
             "job": f.get("秋招岗位", ""),
             "url": f.get("投递链接"),
             "deadline": f.get("投递截止时间", 0),
             "apply_date": f.get("投递时间", ""),
             "exam_date": f.get("机考时间", ""),
             "interview1": f.get("一面", ""),
             "interview2": f.get("二面", "")}
            for f in recent
        ]
    }


def get_dashboard_data():
    return {
        "main": get_main_stats(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),}
