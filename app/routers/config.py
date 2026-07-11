"""飞书配置接口：读取/保存 .env、测试飞书连接。"""
import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app import feishu, state

router = APIRouter(prefix="/api/config", tags=["config"])


class FeishuConfig(BaseModel):
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_app_token: str = ""
    main_table_id: str = ""
    discovery_table_id: str = ""


class TestConfig(FeishuConfig):
    pass


def _masked(value: Optional[str], left: int = 6, right: int = 4) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= left + right:
        return value[:2] + "***"
    return value[:left] + "***" + value[-right:]


@router.get("")
def get_config():
    cfg = feishu.get_config()
    required = getattr(feishu, "REQUIRED_CONFIG_KEYS", ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "MAIN_TABLE_ID"])
    missing = [k for k in required if not cfg.get(k)]
    return {
        "configured": not missing,
        "missing": missing,
        "values": {
            "feishu_app_id": cfg.get("FEISHU_APP_ID", ""),
            "feishu_app_secret_masked": _masked(cfg.get("FEISHU_APP_SECRET", "")),
            "feishu_app_token": cfg.get("FEISHU_APP_TOKEN", ""),
            "main_table_id": cfg.get("MAIN_TABLE_ID", ""),
            "discovery_table_id": cfg.get("DISCOVERY_TABLE_ID", ""),
        },
    }


@router.post("")
def save_config(cfg: FeishuConfig):
    current = feishu.get_config()
    payload = {
        "FEISHU_APP_ID": cfg.feishu_app_id.strip() or current.get("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": cfg.feishu_app_secret.strip() or current.get("FEISHU_APP_SECRET", ""),
        "FEISHU_APP_TOKEN": cfg.feishu_app_token.strip() or current.get("FEISHU_APP_TOKEN", ""),
        "MAIN_TABLE_ID": cfg.main_table_id.strip() or current.get("MAIN_TABLE_ID", ""),
        "DISCOVERY_TABLE_ID": cfg.discovery_table_id.strip() or current.get("DISCOVERY_TABLE_ID", ""),
    }
    feishu.save_config(payload)
    state.set_cache({})
    return {"success": True, "message": "飞书配置已保存"}


@router.post("/test")
def test_config(cfg: TestConfig):
    current = feishu.get_config()
    payload = {
        "FEISHU_APP_ID": cfg.feishu_app_id.strip() or current.get("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": cfg.feishu_app_secret.strip() or current.get("FEISHU_APP_SECRET", ""),
        "FEISHU_APP_TOKEN": cfg.feishu_app_token.strip() or current.get("FEISHU_APP_TOKEN", ""),
        "MAIN_TABLE_ID": cfg.main_table_id.strip() or current.get("MAIN_TABLE_ID", ""),
        "DISCOVERY_TABLE_ID": cfg.discovery_table_id.strip() or current.get("DISCOVERY_TABLE_ID", ""),
    }
    try:
        feishu.test_config(payload)
        return {"success": True, "message": "连接成功：已能读取飞书主表"}
    except Exception as e:
        return {"success": False, "error": feishu.friendly_error(e)}
