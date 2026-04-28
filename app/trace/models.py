from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TraceRecord(BaseModel):
    task_id: int
    step_index: int
    node_name: str
    action_type: str | None = None
    action_input: Any | None = None
    observation: Any | None = None
    screenshot_path: str | None = None
    success: bool
    error_message: str | None = None
    cost_ms: int | None = None
