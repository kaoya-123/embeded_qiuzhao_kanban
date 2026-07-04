import os
import re
import json
from datetime import datetime
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from dedupe_utils import (
    discovery_exact_key,
    extract_url_value,
    is_description_like_job,
    normalize_job_name,
)

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"

CAMPUS_RE = re.compile(r"2027届|2027|27届|2026.{0,10}校园招聘|校园招聘|校招|提前批", re.I)
EMBEDDED_RE = re.compile(r"嵌入式|embedded|BSP|驱动|RTOS|FreeRTOS|Linux|MCU|单片机|车载|底层软件|硬件", re.I)
JOB_RE = re.compile(r"[^，。；;\n\r<>]{0,20}(嵌入式|BSP|驱动|RTOS|Linux|MCU|单片机|车载|底层软件)[^，。；;\n\r<>]{0,30}(工程师|开发|岗位|职位)", re.I)

TODAY_MS = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def get_token():
    r = requests.post(
        f"{API}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data)
    return data["tenant_access_token"]


def feishu_get(path, **params):
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {get_token()}"}, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data)
    return data.get("data", {})


def feishu_post(path, payload):
    r = requests.post(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json; charset=utf-8"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data)
    return data


def list_records(table_id):
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        data = feishu_get(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records", **params)
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            return records
        page_token = data.get("page_token")


def url_value(v):
    return extract_url_value(v)


def fetch_page(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        text = r.text or ""
        return r.status_code, r.url, text[:200000]
    except Exception as e:
        return 0, url, str(e)


def clean(s):
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def dedupe_key(company, url, discovery_type, job_name=""):
    return discovery_exact_key(company, url, discovery_type, job_name)


def existing_keys(pool_records):
    keys = set()
    for r in pool_records:
        k = r.get("fields", {}).get("去重Key")
        if k:
            keys.add(k)
    return keys


def infer_direction(text):
    mapping = []
    if re.search(r"BSP|驱动|driver|内核", text, re.I):
        mapping += ["Linux驱动", "BSP"]
    if re.search(r"RTOS|FreeRTOS|实时", text, re.I):
        mapping.append("RTOS")
    if re.search(r"MCU|单片机|STM32", text, re.I):
        mapping.append("MCU裸机")
    if re.search(r"车载|汽车|座舱|智驾", text, re.I):
        mapping.append("车载嵌入式")
    if re.search(r"Linux|应用|终端", text, re.I):
        mapping.append("Linux应用")
    return list(dict.fromkeys(mapping)) or ["其他"]


def main():
    main_records = list_records(MAIN_TABLE_ID)
    pool_records = list_records(DISCOVERY_TABLE_ID)
    seen = existing_keys(pool_records)

    candidates = []
    for r in main_records:
        f = r.get("fields", {})
        company = f.get("公司名称")
        if not company:
            continue
        url = url_value(f.get("招聘入口")) or url_value(f.get("官网")) or url_value(f.get("投递链接"))
        if not url or not url.startswith("http"):
            continue
        candidates.append((company, url))

    created = []
    for company, url in candidates:
        status, final_url, html = fetch_page(url)
        page_text = clean(html)
        if status not in (200, 201, 202, 203, 204, 301, 302, 403):
            continue
        if not CAMPUS_RE.search(page_text):
            continue

        job_match = JOB_RE.search(page_text)
        has_embedded = bool(EMBEDDED_RE.search(page_text))

        if job_match and has_embedded:
            candidate_job = normalize_job_name(job_match.group(0)[:80])
            if is_description_like_job(candidate_job):
                discovery_type = "公司校招开放"
                job_name = "待确认具体岗位"
                directions = []
                confidence = "高" if "2027" in page_text or "27届" in page_text else "中"
            else:
                discovery_type = "嵌入式岗位开放"
                job_name = candidate_job
                directions = infer_direction(job_name + " " + page_text[:5000])
                confidence = "高"
        else:
            discovery_type = "公司校招开放"
            job_name = "待确认具体岗位"
            directions = []
            confidence = "高" if "2027" in page_text or "27届" in page_text else "中"

        key = dedupe_key(company, final_url, discovery_type, job_name)
        if key in seen:
            continue

        title = f"{company}：{discovery_type}"
        if job_name != "待确认具体岗位":
            title += f" - {job_name}"

        fields = {
            "标题": title,
            "疑似公司": company,
            "疑似嵌入式方向": directions,
            "来源平台": "官网",
            "来源链接": {"link": final_url, "text": final_url},
            "投递链接": {"link": final_url, "text": final_url},
            "命中关键词": ",".join(sorted(set(CAMPUS_RE.findall(page_text)[:10]))),
            "发现时间": TODAY_MS,
            "首次发现时间": TODAY_MS,
            "最近检测时间": TODAY_MS,
            "可信度": confidence,
            "处理状态": "待确认",
            "岗位开放状态": "疑似开放" if discovery_type == "公司校招开放" else "已开放",
            "岗位名称": job_name,
            "JD原文": page_text[:1500] if discovery_type == "嵌入式岗位开放" else "检测到公司校招入口开放；尚未解析到具体嵌入式岗位JD，需要进入来源链接确认。",
            "发现类型": discovery_type,
            "是否新增": True,
            "去重Key": key,
        }
        created.append({"fields": fields})
        seen.add(key)

    if created:
        # 飞书批量创建单次最多500，这里足够
        feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records/batch_create", {"records": created})

    print(json.dumps({"checked": len(candidates), "created": len(created), "created_titles": [r["fields"]["标题"] for r in created]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
