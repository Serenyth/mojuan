from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Annotated
import httpx
import sqlite3

from app.deps import require_admin, require_user
from app.db import get_db
from app import settings as settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ConnectionTestIn(BaseModel):
    baseUrl: str | None = None
    apiKey: str | None = None
    model: str | None = None


def _normalize(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


async def _list_models(base_url: str, api_key: str) -> tuple[list[str], str | None]:
    if not base_url:
        return [], "未配置 baseURL"

    local = "localhost" in base_url or "127.0.0.1" in base_url
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=not local) as client:
            response = await client.get(
                f"{_normalize(base_url)}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as error:
        return [], f"请求失败：{error}"

    if response.status_code != 200:
        return [], f"接口返回 {response.status_code}"

    data = response.json()
    models = [item["id"] for item in data.get("data", []) if item.get("id")]
    return models, None


def _settings_payload(conn: sqlite3.Connection) -> dict:
    """GET 与 PUT 共用：在公开设置上补齐系统提示词三字段。

    - agent_system_prompt：实际生效值（自定义优先，否则内置默认）
    - agent_system_prompt_default：内置默认文本（恢复默认用）
    - agent_system_prompt_is_default：当前是否就是默认（'true'/'false'）
    """
    public = settings_store.get_public_settings(conn)
    effective = settings_store.get_effective_agent_prompt(conn)
    public["agent_system_prompt"] = effective
    public["agent_system_prompt_default"] = settings_store.AGENT_SYSTEM_PROMPT_DEFAULT
    public["agent_system_prompt_is_default"] = (
        "true" if effective == settings_store.AGENT_SYSTEM_PROMPT_DEFAULT else "false"
    )
    return public


@router.get("")
def read_settings(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    return {"settings": _settings_payload(conn), "isAdmin": user["isAdmin"]}


@router.put("")
def update_settings(
    payload: dict[str, str],
    admin: Annotated[dict, Depends(require_admin)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    patch = {
        key: value
        for key, value in payload.items()
        if key in settings_store.SETTING_DEFAULTS
        and isinstance(value, str)
        and value != settings_store.MASK
    }

    if not patch:
        raise HTTPException(status_code=400, detail="没有可保存的设置项")

    settings_store.set_settings(conn, patch)
    return {"ok": True, "settings": _settings_payload(conn)}


@router.post("/test-connection")
async def test_connection(
    payload: ConnectionTestIn,
    admin: Annotated[dict, Depends(require_admin)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    current = settings_store.get_settings(conn)
    base_url = payload.baseUrl or current["ai_base_url"]
    api_key = payload.apiKey or current["ai_api_key"]
    model = payload.model or current["ai_model"]

    models, error = await _list_models(base_url, api_key)
    if error:
        raise HTTPException(status_code=400, detail=error)

    if model and models and model not in models:
        return {
            "ok": True,
            "message": f"连通正常，但模型列表中未找到「{model}」",
            "models": models,
        }

    return {"ok": True, "message": "连通正常", "models": models}


@router.get("/models")
async def list_models(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
) -> dict:
    current = settings_store.get_settings(conn)
    models, error = await _list_models(current["ai_base_url"], current["ai_api_key"])
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"models": models}
