from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.graph import AgentRunner, get_task_result
from app.db.database import init_db, list_task_runs, list_trace


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(title="WebTask Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class TaskRequest(BaseModel):
    task: str = Field(..., min_length=2)
    headless: bool | None = None
    max_steps: int = Field(default=12, ge=3, le=30)


@app.on_event("startup")
async def startup() -> None:
    init_db()


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _with_screenshot_url(row: dict[str, Any]) -> dict[str, Any]:
    row["action_input"] = _maybe_json(row.get("action_input"))
    row["observation"] = _maybe_json(row.get("observation"))
    screenshot_path = row.get("screenshot_path")
    if screenshot_path:
        try:
            rel = Path(screenshot_path).resolve().relative_to(STATIC_DIR.resolve())
            row["screenshot_url"] = f"/static/{rel.as_posix()}"
        except ValueError:
            row["screenshot_url"] = None
    else:
        row["screenshot_url"] = None
    return row


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "WebTask Agent",
        "docs": "/docs",
        "local_pages": [
            "/static/pages/search.html",
            "/static/pages/form.html",
            "/static/pages/products.html",
        ],
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/tasks/run")
async def run_task(req: TaskRequest) -> dict[str, Any]:
    runner = AgentRunner(headless=req.headless, max_steps=req.max_steps)
    result = await runner.run(req.task)
    result["trace"] = [_with_screenshot_url(dict(row)) for row in result.get("trace", [])]
    return result


@app.get("/api/tasks")
async def get_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return list_task_runs(limit=limit)


@app.get("/api/tasks/{task_id}/trace")
async def get_trace(task_id: int) -> list[dict[str, Any]]:
    task = await get_task_result(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return [_with_screenshot_url(dict(row)) for row in list_trace(task_id)]


@app.get("/api/tasks/{task_id}/result")
async def get_result(task_id: int) -> dict[str, Any]:
    task = await get_task_result(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
