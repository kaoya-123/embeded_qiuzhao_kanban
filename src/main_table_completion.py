"""主表字段补齐：只生成可审计计划，确认后只写空字段。

设计原则：
- 默认只 preview，不写飞书。
- 只补白名单字段；只补主表为空的字段。
- 每个候选字段都带 source/reason/risk。
- apply 时再次检查主表字段仍为空，避免覆盖用户手动维护内容。
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dedupe_utils import (
    choose_best_pool_record,
    extract_url_value,
    group_records_by_company,
    is_description_like_job,
    merge_pool_fields,
    normalize_company,
    normalize_job_name,
)

LOW_RISK_FIELDS: list[str] = []
MEDIUM_RISK_FIELDS = ["嵌入式方向", "工作地点"]  # 工作地点在本功能里表示“公司所在地/主要办公城市”，可多选
CURATED_FIELDS = ["公司/行业类型", "细分类型", "公司规模", "公司简介"]
AUTO_PROFILE_FIELDS = MEDIUM_RISK_FIELDS + CURATED_FIELDS
WHITELIST = set(AUTO_PROFILE_FIELDS)
MULTI_FIELDS = {"公司/行业类型", "细分类型", "嵌入式方向", "工作地点"}
SINGLE_FIELDS: set[str] = set()
URL_FIELDS: set[str] = set()
DATE_FIELDS: set[str] = set()

PROFILE_PATH = Path(__file__).resolve().parents[1] / "data" / "company_profiles.json"


def load_profiles(path: str | os.PathLike | None = None) -> dict[str, dict[str, Any]]:
    p = Path(path) if path else PROFILE_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


SEED_PROFILE_PATH = Path(__file__).resolve().parents[1] / "data" / "company_profile_seeds.json"
SEED_COMPANIES_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_companies.json"
PROFILE_FIELDS = ["嵌入式方向", "工作地点", "公司/行业类型", "细分类型", "公司规模", "公司简介"]


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        vals = value
    elif value is None or value == "":
        vals = []
    else:
        vals = [value]
    return list(dict.fromkeys(str(v).strip() for v in vals if str(v or "").strip()))


def _profile_from_fields(fields: dict[str, Any], source: str = "main_table") -> dict[str, Any]:
    out: dict[str, Any] = {}
    mapping = {
        "公司/行业类型": ["公司/行业类型", "company_type"],
        "细分类型": ["细分类型", "subtype"],
        "嵌入式方向": ["嵌入式方向", "direction"],
        "公司所在地": ["公司所在地", "主要办公城市", "工作地点", "city"],
        "公司简介": ["公司简介", "intro"],
        "公司规模": ["公司规模", "scale"],
    }
    multi = {"公司/行业类型", "细分类型", "嵌入式方向", "公司所在地"}
    for target, keys in mapping.items():
        value = None
        for key in keys:
            if not is_empty_value(fields.get(key)):
                value = fields.get(key)
                break
        if is_empty_value(value):
            continue
        if target in multi:
            vals = _as_list(value)
            if vals:
                out[target] = vals
        else:
            text = str(value).strip()
            if text:
                out[target] = text[:120] if target == "公司简介" else text
    if out:
        out["source"] = source
        out.setdefault("confidence", "medium" if source != "main_table" else "high")
        out["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    return out


def _merge_profile(base: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], int]:
    merged = dict(base or {})
    changed = 0
    for field in ["公司/行业类型", "细分类型", "嵌入式方向", "公司所在地"]:
        vals = _as_list(incoming.get(field))
        if not vals:
            continue
        current = _as_list(merged.get(field))
        combined = list(dict.fromkeys(current + vals))
        if combined != current:
            merged[field] = combined
            changed += 1
    for field in ["公司规模", "公司简介"]:
        if is_empty_value(merged.get(field)) and not is_empty_value(incoming.get(field)):
            value = str(incoming.get(field)).strip()
            merged[field] = value[:120] if field == "公司简介" else value
            changed += 1
    if changed:
        sources = _as_list(merged.get("source")) + _as_list(incoming.get("source"))
        merged["source"] = "+".join(list(dict.fromkeys(sources))) if sources else "profile_update"
        if incoming.get("confidence") == "high" or merged.get("confidence") == "high":
            merged["confidence"] = "high"
        else:
            merged["confidence"] = incoming.get("confidence") or merged.get("confidence") or "medium"
        merged["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    return merged, changed


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        out = {}
        for item in data:
            if isinstance(item, dict):
                name = normalize_company(item.get("公司名称"))
                if name:
                    out[name] = item
        return out
    return {}


def load_profile_seed_sources() -> dict[str, dict[str, Any]]:
    seeds: dict[str, dict[str, Any]] = {}
    for path, source in [(SEED_PROFILE_PATH, "legacy_seed"), (SEED_COMPANIES_PATH, "seed_companies")]:
        for name, fields in _load_json_dict(path).items():
            company = normalize_company(name or fields.get("公司名称"))
            if not company:
                continue
            prof = _profile_from_fields(fields, source=source)
            if prof:
                merged, _ = _merge_profile(seeds.get(company, {}), prof)
                seeds[company] = merged
    return seeds


def update_company_profiles_from_main(main_recs: list[dict], path: str | os.PathLike | None = None) -> dict[str, Any]:
    profile_path = Path(path) if path else PROFILE_PATH
    existing = load_profiles(profile_path)
    seeds = load_profile_seed_sources()
    changed_companies = []
    created = 0
    field_changes = 0
    companies_seen = []

    for rec in main_recs:
        fields = normalize_main_fields(rec)
        company = normalize_company(fields.get("公司名称"))
        if not company:
            continue
        companies_seen.append(company)
        before_exists = company in existing
        base = dict(existing.get(company, {}))
        total_changed = 0
        for incoming in [seeds.get(company, {}), _profile_from_fields(fields, source="main_table")]:
            if not incoming:
                continue
            base, changed = _merge_profile(base, incoming)
            total_changed += changed
        if total_changed:
            existing[company] = base
            field_changes += total_changed
            changed_companies.append(company)
            if not before_exists:
                created += 1
        elif company not in existing:
            # 留一个空壳，方便后续 AI/联网画像能力识别待补公司；不参与主表写入。
            existing[company] = {"source": "empty_placeholder", "confidence": "low", "updated_at": datetime.now().strftime("%Y-%m-%d")}
            created += 1
            changed_companies.append(company)

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(dict(sorted(existing.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "success": True,
        "profile_path": str(profile_path),
        "companies_scanned": len(list(dict.fromkeys(companies_seen))),
        "profiles_total": len(existing),
        "profiles_created": created,
        "profiles_changed": len(changed_companies),
        "field_changes": field_changes,
        "changed_companies": changed_companies[:80],
    }


def is_empty_value(v: Any) -> bool:
    if v is None or v == "":
        return True
    if isinstance(v, list) and not v:
        return True
    if isinstance(v, dict):
        return not any(v.values())
    return False


def field_options(field_meta: dict[str, Any], field: str) -> set[str]:
    meta = field_meta.get(field) or {}
    opts = meta.get("options") or (meta.get("property", {}) or {}).get("options") or []
    out = set()
    for opt in opts:
        if isinstance(opt, dict):
            name = opt.get("name") or opt.get("text") or opt.get("value")
        else:
            name = opt
        if name:
            out.add(str(name))
    return out


def normalize_main_fields(record: dict) -> dict:
    return record.get("fields", {}) or {}


def main_company(record: dict) -> str:
    return normalize_company(normalize_main_fields(record).get("公司名称"))


def main_record_map(main_recs: list[dict]) -> dict[str, dict]:
    out = {}
    for rec in main_recs:
        name = main_company(rec)
        if name:
            out[name] = rec
    return out


def eligible_pool_records(pool_recs: list[dict]) -> list[dict]:
    out = []
    for rec in pool_recs:
        f = rec.get("fields", {}) or {}
        company = normalize_company(f.get("疑似公司"))
        if not company:
            continue
        if f.get("岗位开放状态") not in ("已开放", "疑似开放"):
            continue
        out.append(rec)
    return out


def url_candidate(value: Any) -> str:
    url = extract_url_value(value)
    return url if url.startswith("http://") or url.startswith("https://") else ""


def infer_job_type(text: str) -> str:
    t = str(text or "")
    if re.search(r"实习|暑期实习|转正实习|校招实习生", t, re.I):
        return ""
    if "提前批" in t:
        return "提前批"
    if "春招" in t:
        return "春招"
    if re.search(r"秋招|秋季校园招聘|正式校招|校园招聘", t):
        return "秋招"
    return ""


def _source(kind: str, field: str, record: dict | None = None, url: str = "", note: str = "") -> dict[str, Any]:
    src = {"kind": kind, "field": field, "note": note}
    if record:
        src["record_id"] = record.get("record_id", "")
        src["confidence"] = (record.get("fields", {}) or {}).get("可信度", "")
    if url:
        src["url"] = url
    return src


def _change(record: dict, field: str, value: Any, source: dict, reason: str, risk: str) -> dict:
    return {
        "record_id": record.get("record_id"),
        "company": main_company(record),
        "field": field,
        "current_value": normalize_main_fields(record).get(field),
        "proposed_value": value,
        "source": source,
        "reason": reason,
        "risk": risk,
    }


def _skip(company: str, field: str, code: str, reason: str) -> dict:
    return {"company": company, "field": field, "reason_code": code, "reason": reason}


def _validate_value(field: str, value: Any, field_meta: dict[str, Any]) -> tuple[bool, Any, str]:
    if field in URL_FIELDS:
        url = url_candidate(value)
        if not url:
            return False, None, "不是有效 http(s) URL"
        return True, url, ""
    if field in MULTI_FIELDS:
        vals = value if isinstance(value, list) else [value]
        vals = [str(v).strip() for v in vals if str(v or "").strip()]
        if not vals:
            return False, None, "空值"
        opts = field_options(field_meta, field)
        if opts:
            allowed = [v for v in vals if v in opts]
            if not allowed:
                return False, None, "候选值不在飞书已有选项中"
            vals = allowed
        return True, list(dict.fromkeys(vals)), ""
    if field in SINGLE_FIELDS:
        val = str(value or "").strip()
        if not val:
            return False, None, "空值"
        opts = field_options(field_meta, field)
        if opts and val not in opts:
            return False, None, "候选值不在飞书已有选项中"
        return True, val, ""
    if field in DATE_FIELDS:
        return (not is_empty_value(value), value, "空值" if is_empty_value(value) else "")
    val = str(value or "").strip()
    if not val:
        return False, None, "空值"
    if field == "公司简介" and len(val) > 120:
        val = val[:120]
    return True, val, ""


def _pool_candidates(company: str, records: list[dict], requested_fields: set[str]) -> dict[str, tuple[Any, dict, str, str]]:
    # 机会发现池后续会废弃；主表补齐不再从机会池自动补投递链接、截止时间、JD、岗位或岗位类型。
    return {}


def _profile_value(profile: dict, field: str) -> Any:
    if field == "工作地点":
        # 兼容未来更准确的字段名；当前飞书字段仍叫“工作地点”。
        return profile.get("公司所在地") or profile.get("主要办公城市") or profile.get("工作地点")
    return profile.get(field)


def _profile_candidates(company: str, profile: dict, requested_fields: set[str]) -> dict[str, tuple[Any, dict, str, str]]:
    out = {}
    for field in AUTO_PROFILE_FIELDS:
        value = _profile_value(profile, field)
        if field in requested_fields and not is_empty_value(value):
            label = "公司所在地/主要办公城市" if field == "工作地点" else field
            out[field] = (
                value,
                _source("company_profile", label, None, note=f"updated_at={profile.get('updated_at', '')}; confidence={profile.get('confidence', '')}"),
                f"主表为空；使用公司画像库中的{label}",
                "medium",
            )
    return out


def merge_ai_profile_candidates(candidates: list[dict[str, Any]], path: str | os.PathLike | None = None, model: str = "") -> dict[str, Any]:
    """把 AI 画像候选保存到本地画像库；不写飞书。"""
    profile_path = Path(path) if path else PROFILE_PATH
    existing = load_profiles(profile_path)
    changed_companies = []
    created = 0
    field_changes = 0
    skipped = []
    now = datetime.now().strftime("%Y-%m-%d")

    for cand in candidates or []:
        company = normalize_company(cand.get("company"))
        fields = cand.get("fields") or {}
        if not company:
            skipped.append({"company": "", "reason": "公司名为空"})
            continue
        before_exists = company in existing
        base = dict(existing.get(company, {}))
        total_changed = 0

        incoming: dict[str, Any] = {}
        for field in PROFILE_FIELDS:
            if field not in WHITELIST:
                continue
            value = fields.get(field)
            if is_empty_value(value):
                continue
            if field in {"嵌入式方向", "工作地点", "公司/行业类型", "细分类型"}:
                vals = _as_list(value)
                if vals:
                    target = "公司所在地" if field == "工作地点" else field
                    incoming[target] = vals
            elif field == "公司简介":
                text = str(value).strip()[:120]
                if text:
                    incoming[field] = text
            elif field == "公司规模":
                text = str(value).strip()
                if text:
                    incoming[field] = text
        if not incoming:
            skipped.append({"company": company, "reason": "没有可保存的白名单字段"})
            continue

        incoming["source"] = "ai_claude"
        incoming["confidence"] = cand.get("confidence") if cand.get("confidence") in ("low", "medium", "high") else "medium"
        incoming["updated_at"] = now
        base, changed = _merge_profile(base, incoming)
        total_changed += changed

        if total_changed:
            sources = base.get("sources") if isinstance(base.get("sources"), list) else []
            for src in cand.get("sources") or []:
                if isinstance(src, dict) and src not in sources:
                    sources.append(src)
            if sources:
                base["sources"] = sources[:20]
            reasoning = str(cand.get("reasoning") or "").strip()
            if reasoning:
                base["reasoning"] = reasoning[:500]
            base["ai"] = {
                "provider": "anthropic",
                "model": model or cand.get("model") or "claude-opus-4-8",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }
            existing[company] = base
            field_changes += total_changed
            changed_companies.append(company)
            if not before_exists:
                created += 1
        else:
            skipped.append({"company": company, "reason": "本地画像已有等价或更完整字段，未覆盖"})

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(dict(sorted(existing.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "success": True,
        "profile_path": str(profile_path),
        "profiles_total": len(existing),
        "profiles_created": created,
        "profiles_changed": len(changed_companies),
        "field_changes": field_changes,
        "changed_companies": changed_companies[:80],
        "skipped": skipped[:80],
    }



def build_completion_preview(main_recs: list[dict], pool_recs: list[dict], field_meta: dict[str, Any], requested_fields: list[str], include_curated=True, include_medium_risk=True, profiles: dict[str, dict] | None = None) -> dict:
    requested = set(requested_fields or default_requested_fields())
    changes_by_record: dict[str, dict] = {}
    skips = []
    profiles = profiles if profiles is not None else load_profiles()
    main_map = main_record_map(main_recs)
    eligible: dict[str, list[dict]] = {}

    for company, rec in main_map.items():
        fields = normalize_main_fields(rec)
        pool_candidates = _pool_candidates(company, eligible.get(company, []), requested)
        profile_candidates = _profile_candidates(company, profiles.get(company, {}), requested) if include_curated else {}
        candidates = {**pool_candidates, **profile_candidates}
        for field in requested:
            if field not in WHITELIST:
                skips.append(_skip(company, field, "field_not_whitelisted", "字段不在补齐白名单中"))
                continue
            if field in MEDIUM_RISK_FIELDS and not include_medium_risk:
                skips.append(_skip(company, field, "medium_risk_disabled", "嵌入式方向/公司所在地补齐未启用"))
                continue
            if field in CURATED_FIELDS and not include_curated:
                skips.append(_skip(company, field, "curated_disabled", "公司画像补齐未启用"))
                continue
            if not is_empty_value(fields.get(field)):
                skips.append(_skip(company, field, "main_value_present", "主表已有值，按规则不覆盖"))
                continue
            cand = candidates.get(field)
            if not cand:
                skips.append(_skip(company, field, "no_source_value", "没有可靠来源值"))
                continue
            value, source, reason, risk = cand
            ok, value, err = _validate_value(field, value, field_meta)
            if not ok:
                skips.append(_skip(company, field, "invalid_value", err))
                continue
            item = _change(rec, field, value, source, reason, risk)
            bucket = changes_by_record.setdefault(rec.get("record_id"), {"record_id": rec.get("record_id"), "company": company, "fields": []})
            bucket["fields"].append(item)

    changes = list(changes_by_record.values())
    return {
        "summary": {
            "companies_scanned": len(main_map),
            "records_with_changes": len(changes),
            "field_changes": sum(len(c["fields"]) for c in changes),
            "skipped": len(skips),
        },
        "changes": changes,
        "skips": skips[:300],
    }


def flatten_selected(plan: dict, selected: list[dict] | None = None) -> dict[tuple[str, str], dict]:
    allowed = {}
    selected_set = None
    if selected:
        selected_set = set()
        for item in selected:
            rid = item.get("record_id")
            for f in item.get("fields", []):
                selected_set.add((rid, f))
    for group in plan.get("changes", []):
        rid = group.get("record_id")
        for item in group.get("fields", []):
            key = (rid, item.get("field"))
            if selected_set is None or key in selected_set:
                allowed[key] = item
    return allowed


def build_apply_updates(plan: dict, latest_main_recs: list[dict], field_meta: dict[str, Any], selected: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    latest = {r.get("record_id"): r for r in latest_main_recs}
    chosen = flatten_selected(plan, selected)
    per_record = defaultdict(dict)
    skipped = []
    for (rid, field), item in chosen.items():
        rec = latest.get(rid)
        if not rec:
            skipped.append({"record_id": rid, "field": field, "reason_code": "record_missing", "reason": "主表记录不存在"})
            continue
        if not is_empty_value(normalize_main_fields(rec).get(field)):
            skipped.append({"record_id": rid, "field": field, "reason_code": "main_value_changed", "reason": "预览后该字段已有值，未覆盖"})
            continue
        ok, value, err = _validate_value(field, item.get("proposed_value"), field_meta)
        if not ok:
            skipped.append({"record_id": rid, "field": field, "reason_code": "invalid_value", "reason": err})
            continue
        per_record[rid][field] = value
    updates = [{"record_id": rid, "fields": fields} for rid, fields in per_record.items() if fields]
    return updates, skipped


def default_requested_fields() -> list[str]:
    return list(AUTO_PROFILE_FIELDS)
