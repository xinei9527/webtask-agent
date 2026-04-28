from __future__ import annotations

import json
from typing import Any

from app.db.database import insert_trace
from app.trace.models import TraceRecord


def _to_json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


class TraceRecorder:
    async def record(
        self,
        task_id: int,
        step_index: int,
        node_name: str,
        action_type: str | None = None,
        action_input: Any | None = None,
        observation: Any | None = None,
        screenshot_path: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        cost_ms: int | None = None,
    ) -> int:
        record = TraceRecord(
            task_id=task_id,
            step_index=step_index,
            node_name=node_name,
            action_type=action_type,
            action_input=action_input,
            observation=observation,
            screenshot_path=screenshot_path,
            success=success,
            error_message=error_message,
            cost_ms=cost_ms,
        )
        payload = record.model_dump()
        payload["action_input"] = _to_json_text(payload.get("action_input"))
        payload["observation"] = _to_json_text(payload.get("observation"))
        return insert_trace(payload)
