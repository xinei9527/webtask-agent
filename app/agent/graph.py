from __future__ import annotations

import os
import time
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.agent.actions import PlannerMode
from app.agent.executor import ToolExecutor, run_action_with_retry
from app.agent.intelligence import (
    analyze_task,
    assess_step,
    judge_result,
    reflect_failure,
    score_action,
    synthesize_answer,
)
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
    action_policy: Optional[dict[str, Any]]
    result: Optional[dict[str, Any]]
    error: Optional[str]
    done: bool
    final_result: Optional[str]
    failure_count: int
    history: list[dict[str, Any]]
    started_at: float
    planner_mode: str
    task_blueprint: dict[str, Any]
    recovery_notes: list[dict[str, Any]]
    step_assessments: list[dict[str, Any]]


def _env_headless() -> bool:
    value = os.getenv("WEBTASK_HEADLESS", "true").lower()
    return value not in {"0", "false", "no"}


def _env_planner_mode() -> PlannerMode:
    value = os.getenv("WEBTASK_PLANNER", "hybrid").lower()
    if value not in {"rule", "llm", "hybrid"}:
        raise ValueError("WEBTASK_PLANNER must be one of: rule, llm, hybrid.")
    return value  # type: ignore[return-value]


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

            policy_start = time.time()
            policy = await score_action(
                user_task=state["user_task"],
                task_blueprint=state.get("task_blueprint"),
                observation=state.get("observation"),
                action=action,
                history=state.get("history", []),
                recovery_notes=state.get("recovery_notes", []),
            )
            await trace.record(
                task_id=state["task_id"],
                step_index=state.get("current_step", 0),
                node_name="ai_action_policy",
                action_type="score_action",
                action_input=action,
                observation=policy.model_dump(),
                success=True,
                cost_ms=int((time.time() - policy_start) * 1000),
            )
            return {"action": action, "action_policy": policy.model_dump(), "error": None}
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
                    "args": {"answer": f"Planner failed: {exc}"},
                    "reason": "Planner raised an exception; stop the run.",
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
            "action_policy": state.get("action_policy"),
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
        result = state.get("result") or {}

        assessment = await assess_step(
            user_task=state["user_task"],
            task_blueprint=state.get("task_blueprint"),
            action=state.get("action") or {},
            result=result,
            observation=state.get("observation"),
            history=state.get("history", []),
        )
        step_assessments = list(state.get("step_assessments", []))
        step_assessments.append(assessment.model_dump())
        updates["step_assessments"] = step_assessments
        await trace.record(
            task_id=state["task_id"],
            step_index=max(0, state.get("current_step", 1) - 1),
            node_name="ai_step_critic",
            action_type="assess_step",
            action_input={"action": state.get("action"), "result_success": result.get("success")},
            observation=assessment.model_dump(),
            success=True,
            cost_ms=int((time.time() - start) * 1000),
        )

        if not result.get("success") and not updates.get("done"):
            reflection_start = time.time()
            reflection = await reflect_failure(
                user_task=state["user_task"],
                action=state.get("action") or {},
                error=result.get("error") or "",
                observation=state.get("observation"),
                history=state.get("history", []),
            )
            recovery_notes = list(state.get("recovery_notes", []))
            recovery_notes.append(reflection.model_dump())
            updates["recovery_notes"] = recovery_notes
            await trace.record(
                task_id=state["task_id"],
                step_index=max(0, state.get("current_step", 1) - 1),
                node_name="ai_failure_reflector",
                action_type="reflect_failure",
                action_input={
                    "action": state.get("action"),
                    "error": result.get("error"),
                },
                observation=reflection.model_dump(),
                success=True,
                cost_ms=int((time.time() - reflection_start) * 1000),
            )

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
    def __init__(
        self,
        headless: bool | None = None,
        max_steps: int = 12,
        planner_mode: PlannerMode | None = None,
    ):
        self.headless = _env_headless() if headless is None else headless
        self.max_steps = max_steps
        self.planner_mode = planner_mode or _env_planner_mode()

    async def run(self, user_task: str) -> dict[str, Any]:
        task_id = create_task_run(user_task)
        session = BrowserSession()
        started_at = time.time()

        try:
            trace = TraceRecorder()
            blueprint = await analyze_task(user_task)
            await trace.record(
                task_id=task_id,
                step_index=-1,
                node_name="ai_task_analyzer",
                action_type="analyze_task",
                action_input={"user_task": user_task},
                observation=blueprint.model_dump(),
                success=True,
                cost_ms=int((time.time() - started_at) * 1000),
            )

            page = await session.start(headless=self.headless)
            tools = BrowserTools(page)
            planner = HybridPlanner(mode=self.planner_mode)
            graph = build_agent_graph(page, tools, trace, planner)

            final_state = await graph.ainvoke(
                {
                    "task_id": task_id,
                    "user_task": user_task,
                    "current_step": 0,
                    "max_steps": self.max_steps,
                    "observation": {},
                    "action": None,
                    "action_policy": None,
                    "result": None,
                    "error": None,
                    "done": False,
                    "final_result": None,
                    "failure_count": 0,
                    "history": [],
                    "started_at": started_at,
                    "planner_mode": self.planner_mode,
                    "task_blueprint": blueprint.model_dump(),
                    "recovery_notes": [],
                    "step_assessments": [],
                },
                config={"recursion_limit": self.max_steps * 5},
            )

            error = final_state.get("error")
            raw_final_result = final_state.get("final_result")
            judgement_start = time.time()
            judgement = await judge_result(
                user_task=user_task,
                final_result=raw_final_result,
                error=error,
                history=final_state.get("history", []),
            )
            await trace.record(
                task_id=task_id,
                step_index=final_state.get("current_step", 0),
                node_name="ai_result_judge",
                action_type="judge_result",
                action_input={
                    "user_task": user_task,
                    "final_result": raw_final_result,
                    "error": error,
                },
                observation=judgement.model_dump(),
                success=judgement.passed,
                error_message=None if judgement.passed else judgement.rationale,
                cost_ms=int((time.time() - judgement_start) * 1000),
            )

            synthesis_start = time.time()
            synthesis = await synthesize_answer(
                user_task=user_task,
                final_result=raw_final_result,
                error=error,
                judgement=judgement,
                history=final_state.get("history", []),
            )
            await trace.record(
                task_id=task_id,
                step_index=final_state.get("current_step", 0),
                node_name="ai_answer_synthesizer",
                action_type="synthesize_answer",
                action_input={
                    "user_task": user_task,
                    "final_result": raw_final_result,
                    "error": error,
                },
                observation=synthesis.model_dump(),
                success=bool(synthesis.answer),
                cost_ms=int((time.time() - synthesis_start) * 1000),
            )

            final_result = synthesis.answer if synthesis.answer else raw_final_result
            status = "failed" if error else ("completed" if judgement.passed else "needs_review")
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
                "raw_final_result": raw_final_result,
                "error_message": error,
                "steps": final_state.get("current_step", 0),
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "planner_mode": self.planner_mode,
                "task_blueprint": blueprint.model_dump(),
                "result_judgement": judgement.model_dump(),
                "answer_synthesis": synthesis.model_dump(),
                "trace": list_trace(task_id),
            }

        except Exception as exc:
            update_task_run(task_id, "failed", error_message=str(exc), end=True)
            return {
                "task_id": task_id,
                "status": "failed",
                "final_result": None,
                "raw_final_result": None,
                "error_message": str(exc),
                "steps": 0,
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "planner_mode": self.planner_mode,
                "trace": list_trace(task_id),
            }
        finally:
            await session.close()


async def get_task_result(task_id: int) -> dict[str, Any] | None:
    return get_task_run(task_id)
