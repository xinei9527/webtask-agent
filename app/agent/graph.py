from __future__ import annotations

import os
import time
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.agent.executor import ToolExecutor, run_action_with_retry
from app.agent.planner import HybridPlanner
from app.agent.verifier import verify_state
from app.browser.observer import observe_page
from app.browser.session import BrowserSession
from app.browser.tools import BrowserTools
from app.db.database import create_task_run, get_task_run, list_trace, update_task_run
from app.trace.recorder import TraceRecorder


class AgentState(TypedDict, total=False):
    task_id: int
    user_task: str
    current_step: int
    max_steps: int
    observation: dict[str, Any]
    action: Optional[dict[str, Any]]
    result: Optional[dict[str, Any]]
    error: Optional[str]
    done: bool
    final_result: Optional[str]
    failure_count: int
    history: list[dict[str, Any]]
    started_at: float


def _env_headless() -> bool:
    value = os.getenv("WEBTASK_HEADLESS", "true").lower()
    return value not in {"0", "false", "no"}


def build_agent_graph(
    page: Any,
    tools: BrowserTools,
    trace: TraceRecorder,
    planner: HybridPlanner,
):
    executor = ToolExecutor(tools, trace)

    async def observe_node(state: AgentState) -> AgentState:
        start = time.time()
        observation = await observe_page(page)
        await trace.record(
            task_id=state["task_id"],
            step_index=state.get("current_step", 0),
            node_name="observer",
            action_type="observe_page",
            observation=observation,
            success=True,
            cost_ms=int((time.time() - start) * 1000),
        )
        return {"observation": observation}

    async def planner_node(state: AgentState) -> AgentState:
        start = time.time()
        try:
            action = await planner.next_action(dict(state))
            await trace.record(
                task_id=state["task_id"],
                step_index=state.get("current_step", 0),
                node_name="planner",
                action_type=action.get("tool"),
                action_input=action.get("args", {}),
                observation={"reason": action.get("reason", "")},
                success=True,
                cost_ms=int((time.time() - start) * 1000),
            )
            return {"action": action, "error": None}
        except Exception as exc:
            await trace.record(
                task_id=state["task_id"],
                step_index=state.get("current_step", 0),
                node_name="planner",
                action_type="plan",
                success=False,
                error_message=str(exc),
                cost_ms=int((time.time() - start) * 1000),
            )
            return {
                "action": {
                    "tool": "finish",
                    "args": {"answer": f"Planner 输出失败：{exc}"},
                    "reason": "Planner 异常，终止任务",
                },
                "error": str(exc),
            }

    async def executor_node(state: AgentState) -> AgentState:
        action = state["action"] or {}
        step_index = state.get("current_step", 0)
        result = await run_action_with_retry(executor, state["task_id"], step_index, action)
        history_item = {
            "step_index": step_index,
            "tool": action.get("tool"),
            "args": action.get("args", {}),
            "reason": action.get("reason", ""),
            "success": result.get("success"),
            "output": result.get("output"),
            "error": result.get("error"),
            "screenshot_path": result.get("screenshot_path"),
        }
        history = list(state.get("history", []))
        history.append(history_item)
        return {
            "result": result,
            "history": history,
            "current_step": step_index + 1,
        }

    async def verifier_node(state: AgentState) -> AgentState:
        start = time.time()
        updates = verify_state(dict(state))
        await trace.record(
            task_id=state["task_id"],
            step_index=max(0, state.get("current_step", 1) - 1),
            node_name="verifier",
            action_type="verify",
            observation=updates,
            success=updates.get("error") is None,
            error_message=updates.get("error"),
            cost_ms=int((time.time() - start) * 1000),
        )
        return updates

    def route(state: AgentState) -> str:
        return "end" if state.get("done") else "continue"

    graph = StateGraph(AgentState)
    graph.add_node("observer", observe_node)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("verifier", verifier_node)
    graph.set_entry_point("observer")
    graph.add_edge("observer", "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "verifier")
    graph.add_conditional_edges(
        "verifier",
        route,
        {
            "continue": "observer",
            "end": END,
        },
    )
    return graph.compile()


class AgentRunner:
    def __init__(self, headless: bool | None = None, max_steps: int = 12):
        self.headless = _env_headless() if headless is None else headless
        self.max_steps = max_steps

    async def run(self, user_task: str) -> dict[str, Any]:
        task_id = create_task_run(user_task)
        session = BrowserSession()
        started_at = time.time()

        try:
            page = await session.start(headless=self.headless)
            tools = BrowserTools(page)
            trace = TraceRecorder()
            planner = HybridPlanner()
            graph = build_agent_graph(page, tools, trace, planner)

            final_state = await graph.ainvoke(
                {
                    "task_id": task_id,
                    "user_task": user_task,
                    "current_step": 0,
                    "max_steps": self.max_steps,
                    "observation": {},
                    "action": None,
                    "result": None,
                    "error": None,
                    "done": False,
                    "final_result": None,
                    "failure_count": 0,
                    "history": [],
                    "started_at": started_at,
                },
                config={"recursion_limit": self.max_steps * 5},
            )

            error = final_state.get("error")
            final_result = final_state.get("final_result")
            status = "failed" if error else "completed"
            update_task_run(
                task_id=task_id,
                status=status,
                final_result=final_result,
                error_message=error,
                end=True,
            )
            return {
                "task_id": task_id,
                "status": status,
                "final_result": final_result,
                "error_message": error,
                "steps": final_state.get("current_step", 0),
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "trace": list_trace(task_id),
            }

        except Exception as exc:
            update_task_run(task_id, "failed", error_message=str(exc), end=True)
            return {
                "task_id": task_id,
                "status": "failed",
                "final_result": None,
                "error_message": str(exc),
                "steps": 0,
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "trace": list_trace(task_id),
            }
        finally:
            await session.close()


async def get_task_result(task_id: int) -> dict[str, Any] | None:
    return get_task_run(task_id)
