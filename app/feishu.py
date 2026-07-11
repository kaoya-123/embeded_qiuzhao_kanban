"""飞书 API 封装 + 看板数据读取。"""
import os
import re
from datetime import datetime
from collections import Counter
from urllib.parse import unquote

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

# 缓存 wiki 节点 token -> 多维表格 app_token 的映射，避免每次请求都解析
_APP_TOKEN_CACHE = {}


def parse_app_token(value: str) -> str:
    """从用户输入里提取 app_token / wiki 节点 token。

    支持：
    - 独立多维表格链接 https://xxx.feishu.cn/base/<token>?...
    - 知识库链接        https://xxx.feishu.cn/wiki/<token>?...
    - 直接粘贴的纯 token
    """
    value = (value or "").strip()
    if not value:
        return ""
    m = re.search(r"/(?:base|wiki)/([^/?#]+)", value)
    if m:
        return m.group(1)
    return value


def parse_table_id(value: str) -> str:
    """从用户输入里提取多维表格 table_id（tbl 开头）。

    支持从链接的 ?table=<id> 参数解析，或直接粘贴的纯 table_id。
    """
    value = (value or "").strip()
    if not value:
        return ""
    m = re.search(r"[?&]table=([^&#]+)", value)
    if m:
        return unquote(m.group(1))
    # 看起来是链接但没带 table 参数：无法解析出 table_id
    if "://" in value or "/" in value:
        return ""
    return value


def _apply_config(cfg: dict) -> None:
    global APP_ID, APP_SECRET, APP_TOKEN, MAIN_TABLE_ID
    APP_ID = cfg.get("FEISHU_APP_ID") or ""
    APP_SECRET = cfg.get("FEISHU_APP_SECRET") or ""
    APP_TOKEN = cfg.get("FEISHU_APP_TOKEN") or ""
    MAIN_TABLE_ID = cfg.get("MAIN_TABLE_ID") or ""
    _APP_TOKEN_CACHE.clear()


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
    incoming = {k: (cfg.get(k) or "").strip() for k in CONFIG_KEYS}
    # 兜底：即使前端未解析，服务端也把 URL 归一化成纯 token / table_id。
    if incoming.get("FEISHU_APP_TOKEN"):
        incoming["FEISHU_APP_TOKEN"] = parse_app_token(incoming["FEISHU_APP_TOKEN"])
    raw_token = (cfg.get("FEISHU_APP_TOKEN") or "").strip()
    if not incoming.get("MAIN_TABLE_ID") and raw_token:
        incoming["MAIN_TABLE_ID"] = parse_table_id(raw_token)
    if incoming.get("MAIN_TABLE_ID"):
        incoming["MAIN_TABLE_ID"] = parse_table_id(incoming["MAIN_TABLE_ID"])
    merged.update(incoming)
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
    if isinstance(exc, _FeishuError):
        code = exc.code
        msg = exc.msg
        # 权限相关错误码 — 飞书开放平台文档
        if code in (99991400, 232010, 232011):
            return f"应用没有「多维表格」权限：请在飞书开发者后台 → 权限管理中开通 bitable 相关权限。\n详情：[{code}] {msg}"
        if code in (1254300, 1254003):
            return f"多维表格未授权给应用：请把应用的「多维表格」分享给该应用（或在表格页面添加应用为协作者）。\n详情：[{code}] {msg}"
        if code == 1254100:
            return f"多维表格不存在或已被删除。\n详情：[{code}] {msg}"
        if code == 1254002:
            return f"Table ID 不存在，或应用没有该子表的查看权限。\n详情：[{code}] {msg}"
        if code == 1254041:
            return f"Table ID「{MAIN_TABLE_ID}」在该多维表格中不存在，请检查链接里的 table= 参数是否正确。\n详情：[{code}] {msg}"
        if code in (1254309, 1254310):
            return f"应用没有该多维表格的访问权限：请在飞书多维表格页面 → 右上角「…」→ 更多设置 → 添加协作者，搜索并添加你的飞书应用。\n详情：[{code}] {msg}"
        if code == 99991403:
            return f"知识库访问被拒：应用没有该 wiki 节点的查看权限。请把应用加入知识库空间成员。\n详情：[{code}] {msg}"
        if code in (99991401, 230002):
            return f"wiki 节点不存在或 token 不正确。\n详情：[{code}] {msg}"
        if code in (230001, 99991408):
            return f"应用没有「知识库」权限：请在飞书开发者后台 → 权限管理中开通 wiki 相关权限。\n详情：[{code}] {msg}"
        if code in (10003, 10012, 99991667):
            return f"飞书 token 已过期或应用被禁用，请检查飞书开发者后台。\n详情：[{code}] {msg}"
        return f"飞书 API 错误 [{code}]：{msg}"
    return f"飞书连接失败：{text[:220]}"


def test_config(cfg: dict) -> bool:
    old = get_config()
    _apply_config({k: (cfg.get(k) or "").strip() for k in CONFIG_KEYS})
    try:
        cfg_now = get_config()
        missing = [k for k in REQUIRED_CONFIG_KEYS if not cfg_now.get(k)]
        if missing:
            raise RuntimeError("缺少配置：" + ", ".join(missing))
        _feishu(f"/bitable/v1/apps/{_bitable_app_token()}/tables/{MAIN_TABLE_ID}/records", payload={"page_size": 1})
        return True
    finally:
        _apply_config(old)


# ------- 飞书 API 封装 -------
class _FeishuError(RuntimeError):
    """飞书 API 业务错误，携带 code 和 msg 供 friendly_error 精确诊断。"""
    def __init__(self, d: dict):
        self.code = d.get("code", 0)
        self.msg = d.get("msg", "")
        super().__init__(f"[{self.code}] {self.msg}")


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
        raise _FeishuError(d)
    return d.get("data", {})


def _bitable_app_token():
    """把配置里的 APP_TOKEN 解析成真正的多维表格 app_token。

    支持两种来源：
    - 独立多维表格链接 /base/xxx：xxx 本身就是 app_token，直接用。
    - 知识库链接 /wiki/xxx：xxx 是 wiki 节点 token，需要用 wiki 接口换成
      节点挂载的多维表格 obj_token 才能调 bitable API。
    """
    token = APP_TOKEN or ""
    if not token:
        return token
    if token in _APP_TOKEN_CACHE:
        return _APP_TOKEN_CACHE[token]
    # 优先判断：如果看起来像标准 app_token（bascn/xxx 或直接以 bas/开头），直接使用。
    # wiki 节点 token 通常是 Base64-like 长字符串，不以 bas 开头。
    try:
        node = _feishu("/wiki/v2/spaces/get_node", payload={"token": token}).get("node") or {}
        if node.get("obj_type") == "bitable" and node.get("obj_token"):
            _APP_TOKEN_CACHE[token] = node["obj_token"]
            return node["obj_token"]
    except (_FeishuError, RuntimeError):
        # wiki 查询失败（不是 wiki 节点 token 或没有 wiki 权限），
        # 回退：把 token 原样当 app_token 使用（适配独立多维表格 /base/ 场景）。
        pass
    _APP_TOKEN_CACHE[token] = token
    return token


def list_records(table_id):
    recs, pt = [], None
    while True:
        p = {"page_size": 500}
        if pt:
            p["page_token"] = pt
        data = _feishu(f"/bitable/v1/apps/{_bitable_app_token()}/tables/{table_id}/records", payload=p)
        recs.extend(data.get("items", []))
        if not data.get("has_more"):
            return recs
        pt = data.get("page_token")


def list_fields(table_id):
    data = _feishu(f"/bitable/v1/apps/{_bitable_app_token()}/tables/{table_id}/fields", payload={"page_size": 200})
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
             "interview2": f.get("二面", ""),
             "interview3": f.get("三面", ""),
             "warm": f.get("保温", ""),
             "result": f.get("结果", "")}
            for f in recent
        ]
    }


def get_dashboard_data():
    return {
        "main": get_main_stats(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),}
