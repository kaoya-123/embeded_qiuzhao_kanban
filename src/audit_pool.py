"""
嵌入式秋招雷达 - 机会池去重 & 质量审计脚本
每次扫描后必须运行此脚本，确保数据质量。
"""
import argparse
from collections import defaultdict
import requests
import os
from dotenv import load_dotenv

from dedupe_utils import (
    choose_best_pool_record,
    discovery_cluster_key,
    is_description_like_job,
    normalize_company,
    normalize_job_name,
    score_pool_record,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
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


def list_records(table_id):
    t = token()
    records, pt = [], None
    while True:
        params = {"page_size": 100}
        if pt:
            params["page_token"] = pt
        r = requests.get(f"{API}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
                         headers={"Authorization": f"Bearer {t}"}, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(d)
        records.extend(d["data"]["items"])
        if not d["data"].get("has_more"):
            return records
        pt = d["data"].get("page_token")


def feishu_post(path, payload):
    t = token()
    r = requests.post(f"{API}{path}",
                      headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=utf-8"},
                      json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(d)
    return d


def _title(record):
    fields = record.get("fields", {})
    return fields.get("标题") or f"{fields.get('疑似公司','')} - {fields.get('岗位名称','')}"


def _is_invalid(record):
    fields = record.get("fields", {})
    title = fields.get("标题") or ""
    job = normalize_job_name(fields.get("岗位名称"))
    company = normalize_company(fields.get("疑似公司"))
    joined = f"{title}\n{job}\n{fields.get('来源链接','')}\n{fields.get('投递链接','')}"
    invalid_patterns = [
        "位 需求岗位", "026-06-25", "位 確保位",
        "chrome-error", "about:blank",
    ]
    if not company:
        return True, "空公司名"
    for pat in invalid_patterns:
        if pat in joined:
            return True, pat
    return False, ""


def audit_and_dedup(dry_run=False):
    """审计机会池并去重。dry_run=True 时只打印，不删除飞书记录。"""
    records = list_records(DISCOVERY_TABLE_ID)
    print(f"[审计] 机会池总数: {len(records)}")

    to_delete = {}
    valid_records = []

    # 规则1：删除明显脏数据。
    for record in records:
        invalid, reason = _is_invalid(record)
        if invalid:
            to_delete[record["record_id"]] = f"脏数据: {reason}"
            print(f"  [脏数据] {record['record_id']} {reason}: {_title(record)[:70]}")
        else:
            valid_records.append(record)

    # 规则2：按语义机会簇去重，保留质量最高的一条。
    groups = defaultdict(list)
    for record in valid_records:
        groups[discovery_cluster_key(record.get("fields", {}))].append(record)

    for cluster_key, recs in groups.items():
        if len(recs) <= 1:
            continue
        keeper = choose_best_pool_record(recs)
        keeper_id = keeper["record_id"]
        print(f"  [簇去重] {cluster_key} | keep={keeper_id} score={score_pool_record(keeper)} {_title(keeper)[:70]}")
        for record in recs:
            if record["record_id"] == keeper_id:
                continue
            reason = "同机会簇低质量重复"
            job = record.get("fields", {}).get("岗位名称")
            if is_description_like_job(job):
                reason = "岗位名是JD职责句"
            to_delete[record["record_id"]] = reason
            print(f"    delete={record['record_id']} score={score_pool_record(record)} reason={reason}: {_title(record)[:70]}")

    # 规则3：同公司已有岗位级记录时，删除低质量公司级记录。
    companies_with_job = set()
    for record in valid_records:
        fields = record.get("fields", {})
        if record["record_id"] in to_delete:
            continue
        if fields.get("发现类型") == "嵌入式岗位开放":
            companies_with_job.add(normalize_company(fields.get("疑似公司")))

    for record in valid_records:
        fields = record.get("fields", {})
        company = normalize_company(fields.get("疑似公司"))
        if record["record_id"] in to_delete:
            continue
        if fields.get("发现类型") == "公司校招开放" and company in companies_with_job:
            to_delete[record["record_id"]] = "已有嵌入式岗位开放记录，删除公司级冗余"
            print(f"  [冗余] {record['record_id']} {company}: {_title(record)[:70]}")

    delete_ids = list(to_delete)
    if delete_ids:
        if dry_run:
            print(f"[审计] dry-run：将删除 {len(delete_ids)} 条，未写入飞书")
        else:
            for i in range(0, len(delete_ids), 500):
                batch = delete_ids[i:i+500]
                feishu_post(f"/bitable/v1/apps/{APP_TOKEN}/tables/{DISCOVERY_TABLE_ID}/records/batch_delete",
                            {"records": batch})
            print(f"[审计] 共删除 {len(delete_ids)} 条")
    else:
        print("[审计] 无需清理，数据干净")

    return len(delete_ids)


def validate_deadlines():
    """校验机会池和主表的截止时间准确性"""
    KNOWN_DEADLINES = {
        "大疆": "招满即止（网申6月25日开启，RM/RC福利通道7月10日18:00截止）",
        "拓竹": "招满即止（7月5日前投递享第一批快速通道，最快7月录用）",
        "中兴通讯": "2026年8月29日（6月下旬启动→7月上旬面试→8月下旬截止）",
        "禾赛": "2026年8月31日",
        "高德红外": "2027年1月31日",
        "格见半导体": "2026年7月4日截止",
        "航天科技集团": "2026年7月初（各二级单位不同，约7月3日-8日）",
        "长江存储": "招满即止（未设明确截止日，参考：8月29日前）",
        "长鑫存储": "招满即止（5月30日启动，双保险机制：提前批落选可参加正式批）",
        "TP-LINK": "招满即止（提前批5月28日启动，笔试6月中旬，offer 6月底）",
    }

    print("\n[截止时间校验]")
    pool_recs = list_records(DISCOVERY_TABLE_ID)
    for r in pool_recs:
        f = r.get("fields", {})
        company = normalize_company(f.get("疑似公司"))
        if company in KNOWN_DEADLINES:
            expected = KNOWN_DEADLINES[company]
            current_jd = (f.get("JD原文") or "")[:200]
            has_deadline = any(kw in current_jd for kw in ["截止", "招满即止", "月", "日截止"])
            if not has_deadline:
                print(f"  [WARN] {company}: JD lack deadline, expected: {expected}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="机会池去重与质量审计")
    parser.add_argument("--dry-run", action="store_true", help="只打印将删除的记录，不写入飞书")
    args = parser.parse_args()
    deleted = audit_and_dedup(dry_run=args.dry_run)
    validate_deadlines()
    print(f"\n=== audit done, deleted {deleted}, dry_run={args.dry_run} ===")
