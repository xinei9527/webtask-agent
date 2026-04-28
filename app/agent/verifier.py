from __future__ import annotations

from typing import Any


def verify_state(state: dict[str, Any]) -> dict[str, Any]:
    action = state.get("action") or {}
    result = state.get("result") or {}
    tool = action.get("tool")

    if tool == "finish" and result.get("success"):
        return {
            "done": True,
            "final_result": str(result.get("output", "")),
            "error": None,
        }

    if not result.get("success"):
        failure_count = int(state.get("failure_count", 0)) + 1
        if failure_count >= 3:
            return {
                "done": True,
                "failure_count": failure_count,
                "final_result": None,
                "error": result.get("error") or "Action failed 3 times; task stopped.",
            }
        return {
            "done": False,
            "failure_count": failure_count,
            "error": result.get("error"),
        }

    if int(state.get("current_step", 0)) >= int(state.get("max_steps", 12)):
        return {
            "done": True,
            "final_result": None,
            "error": "Reached max_steps; task stopped.",
        }

    return {
        "done": False,
        "failure_count": 0,
        "error": None,
    }
