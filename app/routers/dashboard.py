"""看板数据接口：GET /api/dashboard 返回主表+机会池统计（结构与原 /data 一致）。

关键：连不上飞书（如网络出口在境外、API 被墙）时，返回结构化 JSON + error 字段，
绝不抛 500 让前端拿到 HTML 错误页导致 JSON.parse 崩溃。
"""
from datetime import datetime

from fastapi import APIRouter

from app import feishu, state

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _empty(error: str) -> dict:
    """飞书不可达时的降级空数据，结构与正常返回一致，附带 error 供前端提示。"""
    return {
        "main": {
            "total_companies": 0, "total_progress": 0, "p0_count": 0, "progress": [],
            "exam_count": 0, "interview_count": 0, "offer_count": 0,
            "directions": [], "ctypes": [], "recent": [],
        },
        "pool": {"total": 0, "rows": []},
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": error,
    }


def _friendly(exc: Exception) -> str:
    text = str(exc)
    if any(k in text for k in ("SSLError", "ConnectionError", "10054", "Max retries", "EOF", "timed out", "Timeout")):
        return "连不上飞书 open.feishu.cn（当前网络出口可能在境外，切回国内网络后恢复）"
    return f"读取飞书数据失败：{text[:200]}"


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
            return {**stale, "error": _friendly(e), "stale": True}
        return _empty(_friendly(e))


@router.post("/refresh")
def refresh_dashboard():
    try:
        data = feishu.get_dashboard_data()
        state.set_cache(data)
        return data
    except Exception as e:
        stale = state.get_cache(max_age=1e9)
        if stale:
            return {**stale, "error": _friendly(e), "stale": True}
        return _empty(_friendly(e))
