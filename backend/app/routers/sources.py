"""导入侧：材料的上传与内容归一化。

一路入口收三种材料（文件 / 链接 / 粘贴原文），统一归一化成 Markdown 后
落盘，返回预览。提取层（模式 A / 模式 B）只消费归一化结果，不接触原始格式。

链接路的抓取与落盘在 app.lib.sources（agent 的 fetch_url 共用），
这里只做 HTTP 层的校验与响应。
"""

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.db import DATA_DIR, UPLOAD_DIR, get_db, new_id
from app.deps import require_source, require_user
from app.lib.normalize import NormalizeError, normalize_bytes, normalize_pasted
from app.lib.sources import create_url_source, persist, persist_images

router = APIRouter()

PREVIEW_CHARS = 4000


def _meta(row) -> dict:
    try:
        return json.loads(row["meta"]) if row["meta"] else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _source_dict(row, preview: str | None = None) -> dict:
    payload = {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "status": row["status"],
        "error": row["error"],
        "charCount": row["char_count"],
        "createdAt": row["created_at"],
        "meta": _meta(row),
    }
    if preview is not None:
        payload["preview"] = preview
    return payload


def _read_normalized(row) -> str:
    if not row["normalized_path"]:
        return ""
    path = DATA_DIR / row["normalized_path"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


@router.get("/api/sources")
def get_sources(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    limit: int = 50,
):
    rows = conn.execute(
        "SELECT * FROM sources WHERE owner_id = ? ORDER BY created_at DESC, id LIMIT ?",
        (user["id"], max(1, min(limit, 200))),
    ).fetchall()
    return {"sources": [_source_dict(row) for row in rows]}


@router.post("/api/sources")
async def post_sources(
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    text: str | None = Form(default=None),
):
    provided = [item for item in (file, url, text) if item not in (None, "")]
    if len(provided) != 1:
        raise HTTPException(status_code=422, detail="文件、链接、原文三者只能给一样")

    # 链接路与 agent 的 fetch_url 同源：抓取、落盘、建材料一气呵成
    if url:
        row, error = create_url_source(conn, user["id"], url.strip())
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        return {"source": _source_dict(row, _read_normalized(row)[:PREVIEW_CHARS])}

    source_id = new_id()
    raw: bytes | None = None
    name = ""
    kind = "document"

    try:
        if file is not None:
            name = file.filename or "未命名文件"
            raw = await file.read()
            normalized = normalize_bytes(name, raw)
            kind = normalized.kind
        else:
            stripped = (text or "").strip()
            name = stripped.splitlines()[0][:60] if stripped else "粘贴的原文"
            normalized = normalize_pasted(text or "")
            kind = "text"
    except NormalizeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"读取材料失败：{error}") from error

    meta = dict(normalized.meta)
    meta["kind"] = kind

    image_paths = persist_images(source_id, normalized.images)
    if image_paths:
        meta["images"] = image_paths
        meta["imageCount"] = len(image_paths)

    storage_path, normalized_path = persist(source_id, name, raw, normalized)

    conn.execute(
        """INSERT INTO sources
           (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta)
           VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)""",
        (
            source_id,
            user["id"],
            kind,
            name[:200],
            storage_path,
            normalized_path,
            len(normalized.markdown),
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return {"source": _source_dict(row, normalized.markdown[:PREVIEW_CHARS])}


@router.get("/api/sources/{source_id}")
def get_sources_by_source_id(
    source_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = require_source(conn, source_id, user)
    return {"source": _source_dict(row, _read_normalized(row))}


@router.get("/api/sources/{source_id}/status")
def get_sources_by_source_id_status(
    source_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = require_source(conn, source_id, user)
    return {"source": _source_dict(row)}


@router.delete("/api/sources/{source_id}")
def delete_sources_by_source_id(
    source_id: str,
    user: Annotated[dict, Depends(require_user)],
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = require_source(conn, source_id, user)

    for column in ("storage_path", "normalized_path"):
        relative = row[column]
        if not relative:
            continue
        path = DATA_DIR / relative
        if path.is_file():
            path.unlink(missing_ok=True)

    # 网页图片按 url-img-N 另外落盘，storage_path 里没有，清整个目录
    upload_dir = UPLOAD_DIR / source_id
    if upload_dir.is_dir():
        for stale in upload_dir.iterdir():
            if stale.is_file():
                stale.unlink(missing_ok=True)
        try:
            upload_dir.rmdir()
        except OSError:
            pass

    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    return {"ok": True}
