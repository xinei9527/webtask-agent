from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from app.db.database import get_task_run, list_trace


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _preview(value: Any, limit: int = 260) -> str:
    value = _maybe_json(value)
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    value = " ".join(value.split())
    return value[:limit] + ("..." if len(value) > limit else "")


def classify_failure(error_message: str | None) -> str:
    if not error_message:
        return "none"

    text = error_message.lower()
    if "json" in text or "validation" in text or "schema" in text:
        return "json_or_schema_error"
    if "timeout" in text or "timed out" in text:
        return "page_timeout"
    if "not found" in text or "locator" in text or "strict mode" in text:
        return "element_locator_error"
    if "openai" in text or "api_key" in text or "llm" in text:
        return "llm_config_or_call_error"
    if "maximum" in text or "recursion" in text or "max step" in text:
        return "step_limit_error"
    return "execution_error"


def normalize_trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        item = dict(row)
        item["action_input"] = _maybe_json(item.get("action_input"))
        item["observation"] = _maybe_json(item.get("observation"))
        item["success"] = bool(item.get("success"))
        item["failure_type"] = classify_failure(item.get("error_message"))
        normalized.append(item)
    return normalized


def build_trace_summary(task: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    rows = normalize_trace_rows(trace)
    executor_rows = [row for row in rows if row.get("node_name") == "executor"]
    failed_rows = [row for row in rows if not row.get("success")]
    ai_task_row = next((row for row in rows if row.get("node_name") == "ai_task_analyzer"), None)
    ai_judge_row = next((row for row in rows if row.get("node_name") == "ai_result_judge"), None)
    reflection_rows = [row for row in rows if row.get("node_name") == "ai_failure_reflector"]
    screenshots = [row.get("screenshot_path") for row in rows if row.get("screenshot_path")]
    tool_counts = Counter(row.get("action_type") or "unknown" for row in executor_rows)
    node_counts = Counter(row.get("node_name") or "unknown" for row in rows)
    failure_counts = Counter(row["failure_type"] for row in failed_rows)

    return {
        "task_id": task.get("id"),
        "status": task.get("status"),
        "user_task": task.get("user_task"),
        "final_result": task.get("final_result"),
        "error_message": task.get("error_message"),
        "start_time": task.get("start_time"),
        "end_time": task.get("end_time"),
        "trace_events": len(rows),
        "executor_steps": len(executor_rows),
        "success_events": len(rows) - len(failed_rows),
        "failed_events": len(failed_rows),
        "total_recorded_cost_ms": sum(int(row.get("cost_ms") or 0) for row in rows),
        "screenshot_count": len(set(screenshots)),
        "tool_counts": dict(tool_counts),
        "node_counts": dict(node_counts),
        "failure_counts": dict(failure_counts),
        "first_error": next((row.get("error_message") for row in failed_rows if row.get("error_message")), None),
        "ai_task_blueprint": ai_task_row.get("observation") if ai_task_row else None,
        "ai_result_judgement": ai_judge_row.get("observation") if ai_judge_row else None,
        "ai_failure_reflections": [row.get("observation") for row in reflection_rows],
    }


def build_timeline(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step_index": row.get("step_index"),
            "node_name": row.get("node_name"),
            "action_type": row.get("action_type"),
            "success": row.get("success"),
            "cost_ms": row.get("cost_ms"),
            "failure_type": row.get("failure_type"),
            "error_message": row.get("error_message"),
            "screenshot_path": row.get("screenshot_path"),
            "action_input": row.get("action_input"),
            "observation_preview": _preview(row.get("observation")),
        }
        for row in normalize_trace_rows(trace)
    ]


def _format_counter(counter: dict[str, int]) -> str:
    if not counter:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counter.items())


def build_markdown_report(task: dict[str, Any], trace: list[dict[str, Any]]) -> str:
    summary = build_trace_summary(task, trace)
    timeline = build_timeline(trace)
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    lines = [
        f"# WebTask Agent Report #{summary['task_id']}",
        "",
        f"- Generated at: {generated_at}",
        f"- Status: {summary['status']}",
        f"- Executor steps: {summary['executor_steps']}",
        f"- Trace events: {summary['trace_events']}",
        f"- Recorded cost: {summary['total_recorded_cost_ms']} ms",
        f"- Screenshots: {summary['screenshot_count']}",
        "",
        "## User Task",
        "",
        str(summary.get("user_task") or ""),
        "",
        "## Final Result",
        "",
        str(summary.get("final_result") or summary.get("error_message") or ""),
        "",
        "## AI Task Blueprint",
        "",
        json.dumps(summary.get("ai_task_blueprint") or {}, ensure_ascii=False, indent=2),
        "",
        "## AI Result Judgement",
        "",
        json.dumps(summary.get("ai_result_judgement") or {}, ensure_ascii=False, indent=2),
        "",
        "## AI Failure Reflections",
        "",
        json.dumps(summary.get("ai_failure_reflections") or [], ensure_ascii=False, indent=2),
        "",
        "## Tool Counts",
        "",
        _format_counter(summary["tool_counts"]),
        "",
        "## Failure Counts",
        "",
        _format_counter(summary["failure_counts"]),
        "",
        "## Timeline",
        "",
    ]

    for item in timeline:
        status = "ok" if item["success"] else "failed"
        lines.append(
            f"- Step {item['step_index']} | {item['node_name']} | "
            f"{item.get('action_type') or '-'} | {status} | {item.get('cost_ms') or 0} ms"
        )
        if item.get("error_message"):
            lines.append(f"  - Error: {item['error_message']}")
        if item.get("observation_preview"):
            lines.append(f"  - Observation: {item['observation_preview']}")
        if item.get("screenshot_path"):
            lines.append(f"  - Screenshot: {item['screenshot_path']}")

    return "\n".join(lines)


def build_task_report(task_id: int) -> dict[str, Any] | None:
    task = get_task_run(task_id)
    if not task:
        return None

    trace = list_trace(task_id)
    return {
        "task": task,
        "summary": build_trace_summary(task, trace),
        "timeline": build_timeline(trace),
        "markdown": build_markdown_report(task, trace),
    }
