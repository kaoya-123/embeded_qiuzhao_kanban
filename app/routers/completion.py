"""主表字段补齐接口：先预览，确认后只写空字段。"""
import os
import sys
import time
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import feishu, state

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from main_table_completion import (  # noqa: E402
    CURATED_FIELDS,
    LOW_RISK_FIELDS,
    MEDIUM_RISK_FIELDS,
    WHITELIST,
    build_apply_updates,
    build_completion_preview,
    default_requested_fields,
    update_company_profiles_from_main,
)

router = APIRouter(prefix="/api/completion", tags=["completion"])
_PLAN_TTL = 30 * 60


class PreviewReq(BaseModel):
    fields: list[str] = Field(default_factory=default_requested_fields)
    include_curated: bool = True
    include_medium_risk: bool = True


class ApplyReq(BaseModel):
    plan_id: str
    selected: list[dict[str, Any]] | None = None
    confirm: bool = False


def _plans() -> dict:
    s = state.get()
    return s.get("completion_plans") or {}


def _set_plan(plan_id: str, plan: dict) -> None:
    plans = _plans()
    now = time.time()
    plans = {k: v for k, v in plans.items() if now - v.get("created_at", 0) < _PLAN_TTL}
    plans[plan_id] = plan
    state.update(completion_plans=plans)


def _field_meta():
    return feishu.list_fields(feishu.MAIN_TABLE_ID)


@router.get("/fields")
def fields():
    meta = _field_meta()
    return {
        "fields": [
            {
                "name": name,
                "whitelisted": name in WHITELIST,
                "low_risk": name in LOW_RISK_FIELDS,
                "medium_risk": name in MEDIUM_RISK_FIELDS,
                "curated": name in CURATED_FIELDS,
                "options": [o.get("name") for o in (item.get("property", {}) or {}).get("options", []) if isinstance(o, dict) and o.get("name")],
            }
            for name, item in meta.items()
            if name in WHITELIST
        ],
        "default_fields": default_requested_fields(),
    }


@router.post("/profiles/update")
def update_profiles():
    """更新本地公司画像库，不写飞书主表。"""
    main_recs = feishu.list_records(feishu.MAIN_TABLE_ID)
    result = update_company_profiles_from_main(main_recs)
    return result


@router.post("/preview")
def preview(req: PreviewReq):
    main_recs = feishu.list_records(feishu.MAIN_TABLE_ID)
    meta = _field_meta()
    result = build_completion_preview(
        main_recs,
        [],
        meta,
        req.fields,
        include_curated=req.include_curated,
        include_medium_risk=req.include_medium_risk,
    )
    plan_id = "cmp_" + uuid.uuid4().hex[:12]
    _set_plan(plan_id, {"created_at": time.time(), "result": result, "fields": req.fields})
    return {"plan_id": plan_id, **result}


@router.post("/apply")
def apply(req: ApplyReq):
    if not req.confirm:
        return {"success": False, "error": "必须 confirm=true 才会写入主表"}
    plan = _plans().get(req.plan_id)
    if not plan:
        return {"success": False, "error": "补齐计划不存在或已过期，请重新预览"}
    main_recs = feishu.list_records(feishu.MAIN_TABLE_ID)
    meta = _field_meta()
    updates, skipped = build_apply_updates(plan["result"], main_recs, meta, selected=req.selected)
    applied_records = 0
    if updates:
        applied_records = feishu.batch_update(feishu.MAIN_TABLE_ID, updates)
        try:
            state.set_cache(feishu.get_dashboard_data())
        except Exception:
            pass
    return {
        "success": True,
        "applied_records": applied_records,
        "applied_fields": sum(len(u.get("fields", {})) for u in updates),
        "skipped_on_apply": skipped,
    }
