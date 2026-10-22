from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import (
    auth,
    banks,
    conversations,
    exams,
    extract,
    history,
    practice,
    questions,
    review,
    scripts,
    settings,
    sources,
)

app = FastAPI(title="墨卷 · 刷题训练台", version="0.1.0")

init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    auth,
    settings,
    banks,
    questions,
    sources,
    extract,
    conversations,
    scripts,
    practice,
    review,
    exams,
    history,
):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def _guard_api(full_path: str) -> None:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail=f"接口不存在: /{full_path}")


def _build_frontend_routes() -> None:
    index = FRONTEND_DIST / "index.html"

    if index.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:
            _guard_api(full_path)
            return FileResponse(index)

        return

    @app.get("/{full_path:path}")
    def placeholder(full_path: str) -> HTMLResponse:
        _guard_api(full_path)
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'>"
            "<body style='font-family:system-ui;padding:48px;background:#12100e;color:#ede6dc'>"
            "<h1>墨卷</h1><p>前端尚未构建。</p>"
            "<p>进入 frontend 目录执行：<code>npm install &amp;&amp; npm run build</code></p>"
        )


_build_frontend_routes()
