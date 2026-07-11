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
    load_profiles,
    merge_ai_profile_candidates,
    update_company_profiles_from_main,
)
from ai_company_profile import (  # noqa: E402
    AIProfileError,
    build_company_contexts,
    generate_profile_candidates,
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


class PublicMaterialReq(BaseModel):
    company: str = ""
    title: str = ""
    url: str = ""
    text: str = ""


class AIPreviewReq(BaseModel):
    companies: list[str] = Field(default_factory=list)
    missing_only: bool = True
    include_jd: bool = True
    public_materials: list[PublicMaterialReq] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=default_requested_fields)


class AIApplyLocalReq(BaseModel):
    ai_plan_id: str
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


@router.post("/profiles/ai/preview")
def ai_preview(req: AIPreviewReq):
    """AI 生成公司画像候选：只预览，不写本地画像库，不写飞书。"""
    cfg = feishu.get_config()
    try:
        main_recs = feishu.list_records(feishu.MAIN_TABLE_ID)
        materials = [m.model_dump() if hasattr(m, "model_dump") else m.dict() for m in req.public_materials]
        contexts = build_company_contexts(
            main_recs,
            companies=req.companies,
            public_materials=materials,
            profiles=load_profiles(),
            fields=req.fields,
            missing_only=req.missing_only,
            include_jd=req.include_jd,
        )
        result = generate_profile_candidates(
            contexts,
            api_key=cfg.get("ANTHROPIC_API_KEY", ""),
            model=cfg.get("ANTHROPIC_MODEL", "") or "claude-opus-4-8",
        )
    except AIProfileError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": feishu.friendly_error(e)}

    ai_plan_id = "aip_" + uuid.uuid4().hex[:12]
    candidates = result.get("candidates", [])
    _set_plan(ai_plan_id, {
        "created_at": time.time(),
        "type": "ai_profile",
        "candidates": candidates,
        "model": result.get("model", cfg.get("ANTHROPIC_MODEL", "") or "claude-opus-4-8"),
    })
    return {
        "success": True,
        "ai_plan_id": ai_plan_id,
        "summary": {
            "companies_requested": len(contexts),
            "companies_generated": len(candidates),
            "field_candidates": sum(len(c.get("fields", {})) for c in candidates),
            "warnings": len(result.get("warnings", [])),
        },
        "candidates": candidates,
        "warnings": result.get("warnings", []),
        "model": result.get("model", cfg.get("ANTHROPIC_MODEL", "") or "claude-opus-4-8"),
    }


@router.post("/profiles/ai/apply-local")
def ai_apply_local(req: AIApplyLocalReq):
    """把已预览的 AI 候选保存到本地画像库；不写飞书。"""
    if not req.confirm:
        return {"success": False, "error": "必须 confirm=true 才会保存到本地画像库"}
    plan = _plans().get(req.ai_plan_id)
    if not plan or plan.get("type") != "ai_profile":
        return {"success": False, "error": "AI 画像计划不存在或已过期，请重新生成"}

    candidates = plan.get("candidates", [])
    if req.selected:
        selected_fields = {}
        for item in req.selected:
            company = item.get("company")
            fields = set(item.get("fields") or [])
            if company and fields:
                selected_fields[company] = fields
        filtered = []
        for cand in candidates:
            fields = selected_fields.get(cand.get("company"))
            if not fields:
                continue
            kept = {k: v for k, v in (cand.get("fields") or {}).items() if k in fields}
            if kept:
                item = dict(cand)
                item["fields"] = kept
                filtered.append(item)
        candidates = filtered

    result = merge_ai_profile_candidates(candidates, model=plan.get("model", ""))
    result["next_step"] = "请运行主表补齐预览，确认后再写入飞书主表。"
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
