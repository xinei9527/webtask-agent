from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from app.browser.tools import BrowserTools
from app.trace.recorder import TraceRecorder


MAX_RETRY = 3
ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = ROOT_DIR / "static" / "screenshots"


class ToolExecutor:
    def __init__(self, browser_tools: BrowserTools, trace_recorder: TraceRecorder):
        self.tools = browser_tools
        self.trace = trace_recorder

    async def execute(self, task_id: int, step_index: int, action: dict[str, Any]) -> dict[str, Any]:
        tool = action["tool"]
        args = action.get("args", {})
        start = time.time()
        screenshot_path: str | None = None

        try:
            output = await self._dispatch(tool, args)
            if tool == "screenshot":
                screenshot_path = str(Path(output).resolve())
            elif tool != "finish":
                screenshot_path = await self._safe_step_screenshot(task_id, step_index)

            cost_ms = int((time.time() - start) * 1000)
            await self.trace.record(
                task_id=task_id,
                step_index=step_index,
                node_name="executor",
                action_type=tool,
                action_input=args,
                observation=output,
                screenshot_path=screenshot_path,
                success=True,
                error_message=None,
                cost_ms=cost_ms,
            )
            return {
                "success": True,
                "output": output,
                "error": None,
                "screenshot_path": screenshot_path,
            }

        except Exception as exc:
            cost_ms = int((time.time() - start) * 1000)
            await self.trace.record(
                task_id=task_id,
                step_index=step_index,
                node_name="executor",
                action_type=tool,
                action_input=args,
                observation=None,
                screenshot_path=screenshot_path,
                success=False,
                error_message=str(exc),
                cost_ms=cost_ms,
            )
            return {
                "success": False,
                "output": None,
                "error": str(exc),
                "screenshot_path": screenshot_path,
            }

    async def _dispatch(self, tool: str, args: dict[str, Any]) -> Any:
        if tool == "open_url":
            return await self.tools.open_url(args["url"])
        if tool == "click":
            return await self.tools.click(args["selector_or_text"])
        if tool == "click_by_text":
            return await self.tools.click_by_text(args["text"])
        if tool == "type_text":
            return await self.tools.type_text(args["selector_or_text"], args["text"])
        if tool == "type_by_selector":
            return await self.tools.type_by_selector(args["selector"], args["value"])
        if tool == "type_by_label":
            return await self.tools.type_by_label(args["label"], args["value"])
        if tool == "select_option":
            return await self.tools.select_option(args["selector_or_label"], args["value"])
        if tool == "hover":
            return await self.tools.hover(args["selector_or_text"])
        if tool == "press":
            return await self.tools.press(args["key"])
        if tool == "wait":
            return await self.tools.wait(float(args.get("seconds", 1.0)))
        if tool == "wait_for_text":
            return await self.tools.wait_for_text(args["text"], int(args.get("timeout_ms", 8000)))
        if tool == "extract_text":
            return await self.tools.extract_text(args.get("selector", "body"))
        if tool == "extract_links":
            return await self.tools.extract_links(args.get("selector", "a"), int(args.get("limit", 20)))
        if tool == "extract_table":
            return await self.tools.extract_table(args.get("selector", "table"), int(args.get("limit", 5)))
        if tool == "scroll":
            return await self.tools.scroll(int(args.get("pixels", 800)))
        if tool == "go_back":
            return await self.tools.go_back()
        if tool == "current_page":
            return await self.tools.current_page()
        if tool == "screenshot":
            return await self.tools.screenshot(args["path"])
        if tool == "finish":
            return args["answer"]
        raise ValueError(f"Unknown tool: {tool}")

    async def _safe_step_screenshot(self, task_id: int, step_index: int) -> str | None:
        try:
            path = SCREENSHOT_DIR / f"task_{task_id}_step_{step_index}.png"
            return await self.tools.screenshot(str(path))
        except Exception:
            return None


async def run_action_with_retry(
    executor: ToolExecutor,
    task_id: int,
    step_index: int,
    action: dict[str, Any],
) -> dict[str, Any]:
    last_error = None
    for retry_index in range(MAX_RETRY):
        result = await executor.execute(task_id, step_index, action)
        if result["success"]:
            return result
        last_error = result["error"]
        if retry_index < MAX_RETRY - 1:
            await asyncio.sleep(2)

    return {
        "success": False,
        "output": None,
        "screenshot_path": None,
        "error": f"Action failed after {MAX_RETRY} retries: {last_error}",
    }
