"""
同步：机会发现池 → 主表（投递链接 + 投递截止时间 + 秋招岗位）
只同步「岗位开放状态=已开放」的公司。
规则：
  - 投递链接优先用官方校招入口，非官方链接（高校就业网/mailto/第三方）替换为官方链接
  - 同一主表公司只生成一次 update，避免重复池子记录互相覆盖
"""
import argparse
import os
import json
import requests
from collections import defaultdict
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

# 非官方链接 → 官方校招链接修正表
# 规则：有官网校招入口的必须用官方链接，不要用高校就业网、mailto、第三方平台链接
OFFICIAL_URL_OVERRIDE = {
    "锐明技术": "https://streamax.zhiye.com/campus",
    "比特大陆": "https://jobs.bitmain.com.cn",
    "中国航发涡轮院": "https://zhaopin.aecc.cn",
    "中船凌久电子": "http://www.csic-lincom.cn",
}


def get_token():
    r = requests.post(f"{API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d["tenant_access_token"]


def list_records(table_id, token):
    records, pt = [], None
    while True:
        params = {"page_size": 500}
        if pt:
            params["page_token"] = pt
        r = requests.get(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
                         headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(d)
        records.extend(d.get("data", {}).get("items", []))
        if not d.get("data", {}).get("has_more"):
            return records
        pt = d.get("data", {}).get("page_token")


def batch_update(table_id, records, token):
    payload = {"records": records}
    r = requests.post(
        f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_update",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"batch_update error: {json.dumps(d, ensure_ascii=False)[:800]}")
    return d.get("data", {}).get("records", [])


def build_main_map(main_recs):
    main_map = {}
    display_names = {}
    for r in main_recs:
        name = (r.get("fields", {}).get("公司名称") or "").strip()
        key = normalize_company(name)
        if key and key not in main_map:
            main_map[key] = r["record_id"]
            display_names[r["record_id"]] = name
    return main_map, display_names


def build_updates(pool_recs, main_recs):
    main_map, display_names = build_main_map(main_recs)
    open_pool = []
    skip_not_open = []
    skip_no_match = []

    for record in pool_recs:
        fields = record.get("fields", {})
        pool_company = (fields.get("疑似公司") or "").strip()
        if not pool_company:
            continue
        if fields.get("岗位开放状态", "") != "已开放":
            skip_not_open.append(pool_company)
            continue
        main_company = normalize_company(pool_company)
        if main_company not in main_map:
            skip_no_match.append(pool_company)
            continue
        open_pool.append(record)

    grouped = group_records_by_company(open_pool)
    updates = []
    merge_notes = []

    for company, records in sorted(grouped.items()):
        rid = main_map.get(company)
        if not rid:
            continue
        best = choose_best_pool_record(records)
        merged = merge_pool_fields(records)
        if not best or not merged:
            continue

        fields_patch = {}
        official_url = OFFICIAL_URL_OVERRIDE.get(company)
        if official_url:
            fields_patch["投递链接"] = {"link": official_url, "text": official_url}
        else:
            pool_url = extract_url_value(merged.get("投递链接")) or extract_url_value(merged.get("来源链接"))
            if pool_url and pool_url.startswith("http"):
                fields_patch["投递链接"] = {"link": pool_url, "text": pool_url}

        deadline = merged.get("投递截至时间") or merged.get("投递截止时间")
        if deadline:
            fields_patch["投递截止时间"] = str(deadline)

        job = normalize_job_name(merged.get("岗位名称"))
        if job and job != "待确认具体岗位" and not is_description_like_job(job):
            fields_patch["秋招岗位"] = job

        if fields_patch:
            updates.append({"record_id": rid, "fields": fields_patch})
            if len(records) > 1:
                merge_notes.append({
                    "company": display_names.get(rid, company),
                    "count": len(records),
                    "selected": best.get("record_id", ""),
                    "selected_job": normalize_job_name(best.get("fields", {}).get("岗位名称")),
                })

    return updates, skip_not_open, skip_no_match, merge_notes, display_names


def write_report(path, pool_recs, main_recs, updates, skip_not_open, skip_no_match, merge_notes, display_names):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"Pool: {len(pool_recs)} | Main: {len(display_names)} | Updates: {len(updates)}\n")
        fh.write(f"Skip not_open: {skip_not_open}\n")
        fh.write(f"Skip no_match: {skip_no_match}\n")
        if merge_notes:
            fh.write("Merged duplicate pool records:\n")
            for note in merge_notes:
                fh.write(
                    f"  {note['company']}: merged {note['count']} pool records, "
                    f"selected={note['selected']} | job={note['selected_job'][:80]}\n"
                )
        fh.write("\n")
        for u in updates:
            company_name = display_names.get(u["record_id"], "?")
            fh.write(
                f"  {company_name}: url={str(u['fields'].get('投递链接',''))[:80]} "
                f"| deadline={str(u['fields'].get('投递截止时间',''))[:50]} "
                f"| job={str(u['fields'].get('秋招岗位',''))[:80]}\n"
            )


def main(dry_run=False):
    token = get_token()

    pool_recs = list_records(DISCOVERY_TABLE_ID, token)
    main_recs = list_records(MAIN_TABLE_ID, token)
    print(f"Pool: {len(pool_recs)} | Main: {len(main_recs)}")

    updates, skip_not_open, skip_no_match, merge_notes, display_names = build_updates(pool_recs, main_recs)
    report_path = "sync_report.txt" if not dry_run else "sync_report_dry_run.txt"
    write_report(report_path, pool_recs, main_recs, updates, skip_not_open, skip_no_match, merge_notes, display_names)

    print(f"Updates: {len(updates)} | skip_not_open: {len(skip_not_open)} | skip_no_match: {len(skip_no_match)}")
    if merge_notes:
        print(f"Merged duplicate companies: {len(merge_notes)}")

    if dry_run:
        print(f"Dry-run only. Report written: {report_path}")
        return len(updates)

    if updates:
        result = batch_update(MAIN_TABLE_ID, updates, token)
        print(f"Done! {len(result)} records updated.")
    else:
        print("No updates.")
    return len(updates)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步机会池投递链接、截止时间、岗位到主表")
    parser.add_argument("--dry-run", action="store_true", help="只生成报告，不写入主表")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
