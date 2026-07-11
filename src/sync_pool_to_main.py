"""
机会发现池 → 主表同步脚本
每次扫描后将池中信息同步回主表对应公司。
"""
import os
from datetime import datetime
import requests
from dotenv import load_dotenv, find_dotenv

from dedupe_utils import (
    choose_best_pool_record,
    extract_url_value,
    group_records_by_company,
    is_description_like_job,
    merge_pool_fields,
    normalize_company,
    normalize_job_name,
)

load_dotenv(find_dotenv())

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
MAIN_TABLE_ID = os.getenv("MAIN_TABLE_ID")
DISCOVERY_TABLE_ID = os.getenv("DISCOVERY_TABLE_ID")
API = "https://open.feishu.cn/open-apis"


def token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d["tenant_access_token"]


def feishu_get(path, **params):
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {token()}"},
                     params=params, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d.get("data", {})


def feishu_post(path, payload):
    r = requests.post(f"{API}{path}", headers={"Authorization": f"Bearer {token()}",
                      "Content-Type": "application/json; charset=utf-8"}, json=payload, timeout=30)
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


def url_val(v):
    url = extract_url_value(v)
    if url and url.startswith("http"):
        return {"link": url, "text": url}
    return None


def get_field_map(table_id):
    """拉取主表真实字段，返回 {字段名: 字段ID}。

    只写真实存在的字段，避免把数据写到不存在的字段ID导致整批失败。
    """
    data = feishu_get(f"/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/fields", page_size=200)
    out = {}
    for item in data.get("items", []):
        name = item.get("field_name")
        fid = item.get("field_id")
        if name and fid:
            out[name] = fid
    return out


def _to_id_fields(patch, field_map):
    """把 {中文字段名: 值} 转成 {字段ID: 值}，丢弃主表里不存在的字段。"""
    out = {}
    for name, val in patch.items():
        fid = field_map.get(name)
        if fid:
            out[fid] = val
    return out


def _main_map(main_recs):
    out = {}
    for r in main_recs:
        name = normalize_company(r.get("fields", {}).get("公司名称"))
        if name:
            out[name] = r["record_id"]
    return out


def build_updates(pool_recs, main_recs, field_map):
    main_map = _main_map(main_recs)
    eligible = []
    for r in pool_recs:
        f = r.get("fields", {})
        company = normalize_company(f.get("疑似公司"))
        if not company or company not in main_map:
            continue
        # 只用已开放/疑似开放记录回填，已截止/待确认不覆盖主表。
        if f.get("岗位开放状态") not in ("已开放", "疑似开放"):
            continue
        eligible.append(r)

    updates = []
    for company, records in group_records_by_company(eligible).items():
        rid = main_map.get(company)
        if not rid:
            continue
        best = choose_best_pool_record(records)
        merged = merge_pool_fields(records)
        if not best or not merged:
            continue

        patch = {}
        jd = merged.get("JD原文")
        if jd and len(str(jd)) > 20:
            patch["JD原文"] = str(jd)[:2000]

        status = merged.get("岗位开放状态")
        if status:
            patch["岗位开放状态"] = status

        link = url_val(merged.get("投递链接")) or url_val(merged.get("来源链接"))
        if link:
            patch["投递链接"] = link.get("link", "")

        check_time = merged.get("最近检测时间") or merged.get("发现时间")
        if check_time:
            patch["最近核验时间"] = check_time

        job = normalize_job_name(merged.get("岗位名称"))
        if job and job != "待确认具体岗位" and not is_description_like_job(job):
            patch["秋招岗位"] = job

        if merged.get("可信度") == "高" and merged.get("发现类型") == "嵌入式岗位开放":
            patch["信息核验状态"] = "已核验"

        if patch:
            id_patch = _to_id_fields(patch, field_map)
            if id_patch:
                updates.append({"record_id": rid, "fields": id_patch})
    return updates


def build_creates(pool_recs, main_recs, field_map):
    """机会池里主表还没有的公司，够格的自动新建到主表。

    只建 A 档：发现类型=嵌入式岗位开放 且 可信度=高，且岗位仍开放。
    新建行标记 信息核验状态=待核验，意愿等需人工判断的字段留空。
    """
    main_map = _main_map(main_recs)
    new_eligible = []
    for r in pool_recs:
        f = r.get("fields", {})
        company = normalize_company(f.get("疑似公司"))
        if not company or company in main_map:
            continue
        if f.get("发现类型") != "嵌入式岗位开放":
            continue
        if f.get("可信度") != "高":
            continue
        if f.get("岗位开放状态") not in ("已开放", "疑似开放"):
            continue
        new_eligible.append(r)

    creates = []
    for company, records in group_records_by_company(new_eligible).items():
        merged = merge_pool_fields(records)
        if not merged:
            continue

        fields = {"公司名称": company, "信息核验状态": "待核验"}

        status = merged.get("岗位开放状态")
        if status:
            fields["岗位开放状态"] = status

        link = url_val(merged.get("投递链接")) or url_val(merged.get("来源链接"))
        if link:
            fields["投递链接"] = link.get("link", "")

        job = normalize_job_name(merged.get("岗位名称"))
        if job and job != "待确认具体岗位" and not is_description_like_job(job):
            fields["秋招岗位"] = job

        jd = merged.get("JD原文")
        if jd and len(str(jd)) > 20:
            fields["JD原文"] = str(jd)[:2000]

        check_time = merged.get("最近检测时间") or merged.get("发现时间")
        if check_time:
            fields["最近核验时间"] = check_time

        id_fields = _to_id_fields(fields, field_map)
        if id_fields.get(field_map.get("公司名称")):
            creates.append({"fields": id_fields})
    return creates


def sync_pool_to_main():
    pool_recs = list_records(DISCOVERY_TABLE_ID)
    main_recs = list_records(MAIN_TABLE_ID)
    field_map = get_field_map(MAIN_TABLE_ID)

    # 先新建主表缺失的合格公司，再回填已有公司；两者都基于同一份 main 快照，互不重复。
    creates = build_creates(pool_recs, main_recs, field_map)
    if creates:
        for i in range(0, len(creates), 500):
            batch = creates[i:i+500]
            feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN_TABLE_ID}/records/batch_create",
                        {"records": batch})

    updates = build_updates(pool_recs, main_recs, field_map)
    if updates:
        for i in range(0, len(updates), 500):
            batch = updates[i:i+500]
            feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{MAIN_TABLE_ID}/records/batch_update",
                        {"records": batch})

    return len(creates) + len(updates)


if __name__ == "__main__":
    n = sync_pool_to_main()
    print(f"已同步 {n} 条记录到主表")
