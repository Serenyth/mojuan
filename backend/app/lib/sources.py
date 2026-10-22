"""材料的创建与落盘：路由层与 agent 工具共用。

agent 的 fetch_url 和 POST /api/sources 的链接路必须走同一套逻辑，
否则「对话里抓的链接」和「左侧加的链接」会长出两种存储形态，
提取层（meta.images / normalized_path）对不上。
"""

import json
import re
from pathlib import Path

from app.db import DATA_DIR, NORMALIZED_DIR, UPLOAD_DIR, new_id
from app.lib.normalize import NormalizeError, normalize_url

SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fa5]+")


def safe_filename(name: str) -> str:
    cleaned = SAFE_NAME.sub("_", Path(name).name).strip("._")
    return (cleaned or "file")[:120]


def image_ext(mime: str) -> str:
    subtype = mime.split("/")[-1].strip().lower()
    if subtype == "jpeg":
        return ".jpg"
    return f".{subtype}" if subtype else ".png"


def persist(source_id: str, name: str, raw: bytes | None, normalized) -> tuple[str | None, str | None]:
    """原始文件与归一化结果分别落盘，路径相对 DATA_DIR 存库，便于整体搬迁。"""
    normalized_path = None
    if normalized.markdown:
        NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        path = NORMALIZED_DIR / f"{source_id}.md"
        path.write_text(normalized.markdown, encoding="utf-8")
        normalized_path = path.relative_to(DATA_DIR).as_posix()

    storage_path = None
    if raw is not None:
        target_dir = UPLOAD_DIR / source_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_filename(name)
        target.write_bytes(raw)
        storage_path = target.relative_to(DATA_DIR).as_posix()

    return storage_path, normalized_path


def persist_images(source_id: str, images) -> list[str]:
    """网页里下载的题目图片落盘，返回相对 DATA_DIR 的路径。

    这些图不在 storage_path 里（那不是上传的原始文件），提取层按
    meta.images 读它们走视觉通道。
    """
    saved: list[str] = []
    for index, (data, mime) in enumerate(images, start=1):
        target_dir = UPLOAD_DIR / source_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"url-img-{index}{image_ext(mime)}"
        target.write_bytes(data)
        saved.append(target.relative_to(DATA_DIR).as_posix())
    return saved


def create_url_source(conn, owner_id: str, url: str):
    """抓一个链接并建成材料。返回 (row, error_message)。

    成功时 row 是 sources 行（新建或复用的）；失败时 row 为 None，
    error_message 是给用户/模型看的中文说明。同一链接重复抓取时
    复用旧材料，不重复创建。
    """
    existing = conn.execute(
        "SELECT * FROM sources WHERE owner_id = ? AND name = ?", (owner_id, url)
    ).fetchone()
    if existing is not None:
        return existing, None

    source_id = new_id()
    try:
        normalized = normalize_url(url)
    except NormalizeError as error:
        return None, str(error)
    except Exception as error:  # 抓取过程中的意外（超时、连接重置等）
        return None, f"读取材料失败：{error}"

    meta = dict(normalized.meta)
    meta["kind"] = "url"

    image_paths = persist_images(source_id, normalized.images)
    if image_paths:
        meta["images"] = image_paths
        meta["imageCount"] = len(image_paths)

    storage_path, normalized_path = persist(source_id, url, None, normalized)

    conn.execute(
        """INSERT INTO sources
           (id, owner_id, type, name, storage_path, normalized_path, status, char_count, meta)
           VALUES (?, ?, 'url', ?, ?, ?, 'ready', ?, ?)""",
        (
            source_id,
            owner_id,
            url[:200],
            storage_path,
            normalized_path,
            len(normalized.markdown),
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return row, None
