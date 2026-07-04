import os
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from dedupe_utils import discovery_exact_key, is_description_like_job, normalize_job_name

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"
TODAY_MS = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

EMBEDDED_KEYWORDS = re.compile(r"嵌入式|驱动|BSP|Linux|RTOS|MCU|单片机|芯片验证|芯片设计|GPU系统|底层|车载|电子工程师", re.I)

PAGES = {
    "大疆": "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/jobs",
    "vivo": "https://hr-campus.vivo.com/jobs",
}


def token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal", json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d["tenant_access_token"]


def feishu_get(path, **params):
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {token()}"}, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d.get("data", {})


def feishu_post(path, payload):
    r = requests.post(f"{API}{path}", headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json; charset=utf-8"}, json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d


def list_records(table_id):
    records, pt = [], None
    while True:
        params = {"page_size": 500}
        if pt:
            params["page_token"] = pt
        data = feishu_get(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records", **params)
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            return records
        pt = data.get("page_token")


def existing_keys():
    keys = set()
    for r in list_records(DISCOVERY_TABLE_ID):
        k = r.get("fields", {}).get("去重Key")
        if k:
            keys.add(k)
    return keys


def key(company, job_name, url):
    return discovery_exact_key(company, url, "嵌入式岗位开放", job_name)


def infer_direction(text):
    dirs = []
    if re.search(r"驱动|BSP|内核|driver", text, re.I):
        dirs += ["Linux驱动", "BSP"]
    if re.search(r"Linux|应用", text, re.I):
        dirs.append("Linux应用")
    if re.search(r"RTOS|FreeRTOS|实时", text, re.I):
        dirs.append("RTOS")
    if re.search(r"MCU|单片机|STM32|电子", text, re.I):
        dirs.append("MCU裸机")
    if re.search(r"车载|汽车|座舱|智驾", text, re.I):
        dirs.append("车载嵌入式")
    if re.search(r"芯片|GPU", text, re.I):
        dirs += ["Linux驱动", "BSP"]
    return list(dict.fromkeys(dirs)) or ["其他"]


def cities_from_text(text):
    city_map = {
        "北京": "北京", "上海": "上海", "深圳": "深圳", "杭州": "杭州", "南京": "南京", "西安": "西安", "东莞": "深圳",
        "广州": "广州", "武汉": "武汉", "成都": "成都", "苏州": "苏州", "合肥": "合肥", "宁波": "宁波"
    }
    found = []
    for k, v in city_map.items():
        if k in text and v not in found:
            found.append(v)
    return found


def make_record(company, job_name, url, jd, source_text="官网"):
    job_name = normalize_job_name(job_name)
    if is_description_like_job(job_name):
        return None
    dedupe = key(company, job_name, url)
    return dedupe, {
        "fields": {
            "标题": f"{company}：嵌入式岗位开放 - {job_name}",
            "疑似公司": company,
            "岗位名称": job_name,
            "疑似嵌入式方向": infer_direction(job_name + "\n" + jd),
            "工作地点": cities_from_text(job_name + "\n" + jd),
            "来源平台": "官网",
            "来源链接": {"link": url, "text": source_text},
            "投递链接": {"link": url, "text": "投递/查看岗位"},
            "命中关键词": ",".join(sorted(set(EMBEDDED_KEYWORDS.findall(job_name + "\n" + jd))))[:200],
            "发现时间": TODAY_MS,
            "首次发现时间": TODAY_MS,
            "最近检测时间": TODAY_MS,
            "可信度": "高",
            "处理状态": "待确认",
            "岗位开放状态": "已开放",
            "JD原文": jd[:1800],
            "发现类型": "嵌入式岗位开放",
            "是否新增": True,
            "去重Key": dedupe,
        }
    }


def parse_dji(text, url):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    out = []
    for i, line in enumerate(lines):
        # 当前先只收显式嵌入式岗位，避免把算法/测试岗位混进来
        if line != "嵌入式工程师（上海）":
            continue
        ctx = "\n".join(lines[i:i+80])
        exact_url = "https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/job/c688765c-8541-42a6-9edf-fb23849e65fc"
        rec = make_record("大疆", line, exact_url, ctx, "DJI 2027拓疆者校园招聘-嵌入式工程师")
        if rec:
            out.append(rec)
    return out


def parse_vivo(text, url):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    out = []
    for i, line in enumerate(lines):
        if not EMBEDDED_KEYWORDS.search(line):
            continue
        # 当前只做2027届正式校园招聘/秋招；实习、暑期实习先不入库
        if "实习" in line or "暑期" in line:
            continue
        if len(line) > 80 or line in ("岗位投递", "职位类别", "搜索职位"):
            continue
        ctx = "\n".join(lines[i:i+4])
        rec = make_record("vivo", line, url, ctx, "vivo校园招聘岗位列表")
        if rec:
            out.append(rec)
    return out


def scan_dynamic():
    seen = existing_keys()
    candidates = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        for company, url in PAGES.items():
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(10000)
                text = page.locator("body").inner_text(timeout=20000)
                if company == "大疆":
                    candidates.extend(parse_dji(text, page.url))
                elif company == "vivo":
                    candidates.extend(parse_vivo(text, page.url))
            except Exception as e:
                print(f"{company} error: {e}")
        browser.close()

    records = []
    for dedupe, rec in candidates:
        if dedupe not in seen:
            records.append(rec)
            seen.add(dedupe)
    if records:
        feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records/batch_create", {"records": records})
    return records


if __name__ == "__main__":
    created = scan_dynamic()
    print({"created": len(created), "titles": [r["fields"]["标题"] for r in created]})
