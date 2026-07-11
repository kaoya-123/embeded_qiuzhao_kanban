"""看板数据接口：GET /api/dashboard 返回主表统计。
"""
from datetime import datetime

from fastapi import APIRouter

from app import feishu, state

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _empty(error: str) -> dict:
    """飞书不可达时的降级空数据，结构与正常返回一致，附带 error 供前端提示。"""
    return {
        "main": {
            "total_companies": 0,
            "exam_count": 0, "interview_count": 0, "offer_count": 0,
            "directions": [], "ctypes": [], "recent": [],
        },
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": error,
    }


@router.get("")
def get_dashboard():
    # 30 秒缓存，减少飞书 API 压力
    cached = state.get_cache(max_age=30.0)
    if cached:
        return cached
    try:
        data = feishu.get_dashboard_data()
        state.set_cache(data)
        return data
    except Exception as e:
        # 有旧缓存就返回旧缓存 + 提示；否则返回空结构 + 提示。
        stale = state.get_cache(max_age=1e9)
        if stale:
            return {**stale, "error": feishu.friendly_error(e), "stale": True}
        return _empty(feishu.friendly_error(e))


@router.post("/refresh")
def refresh_dashboard():
    try:
        data = feishu.get_dashboard_data()
        state.set_cache(data)
        return data
    except Exception as e:
        stale = state.get_cache(max_age=1e9)
        if stale:
            return {**stale, "error": feishu.friendly_error(e), "stale": True}
        return _empty(feishu.friendly_error(e))
