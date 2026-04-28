from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st


API_BASE = os.getenv("WEBTASK_API_BASE", "http://localhost:8000")


def _get_json(path: str, timeout: int = 60) -> Any:
    resp = requests.get(f"{API_BASE}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _render_json_block(title: str, value: Any) -> None:
    st.markdown(f"**{title}**")
    st.json(value or {})


st.set_page_config(page_title="WebTask Agent", layout="wide")
st.title("WebTask Agent")
st.caption("Browser task automation with LLM planning, action policy checks, step critique, trace replay, and report generation.")

try:
    runtime_config = _get_json("/api/config", timeout=10)
except Exception:
    runtime_config = {}

with st.sidebar:
    st.header("Runtime")
    st.caption(API_BASE)
    llm_config = runtime_config.get("llm", {})
    if llm_config.get("configured"):
        st.success("LLM connected")
    else:
        st.warning("LLM not configured")
    st.write("Model:", llm_config.get("model", "-"))
    st.write("Base URL:", "configured" if llm_config.get("base_url_configured") else "default")
    st.write("Default planner:", runtime_config.get("planner_default", "hybrid"))
    st.divider()
    st.caption("No API key is shown here. Only configuration status is exposed.")

default_task = "打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接"
task = st.text_area("Browser task", default_task, height=110)

col_run, col_headless, col_steps, col_mode = st.columns([1, 1, 1, 1])
with col_headless:
    headless = st.toggle("Headless", value=True)
with col_steps:
    max_steps = st.number_input("Max steps", min_value=3, max_value=30, value=12)
with col_mode:
    planner_mode = st.selectbox(
        "Planner",
        options=["hybrid", "rule", "llm"],
        index=0,
        help="hybrid uses the LLM when OPENAI_API_KEY is configured, then falls back to rules.",
    )

if col_run.button("Run task", type="primary", use_container_width=True):
    with st.spinner("Agent is controlling the browser..."):
        resp = requests.post(
            f"{API_BASE}/api/tasks/run",
            json={
                "task": task,
                "headless": headless,
                "max_steps": int(max_steps),
                "planner_mode": planner_mode,
            },
            timeout=240,
        )
    if resp.ok:
        data = resp.json()
        st.session_state["last_task_id"] = data["task_id"]
        st.subheader("Final Result")
        if data.get("error_message"):
            st.error(data["error_message"])
        else:
            st.success(data.get("final_result") or "Task completed")
        st.caption(
            f"Task ID: {data['task_id']} | Status: {data['status']} | "
            f"Planner: {data.get('planner_mode')} | Elapsed: {data['elapsed_ms']} ms"
        )
        with st.expander("AI output from this run", expanded=True):
            cols = st.columns(3)
            with cols[0]:
                _render_json_block("Task Blueprint", data.get("task_blueprint"))
            with cols[1]:
                _render_json_block("Result Judgement", data.get("result_judgement"))
            with cols[2]:
                _render_json_block("Answer Synthesis", data.get("answer_synthesis"))
    else:
        st.error(resp.text)

task_id = st.text_input("Trace Task ID", value=str(st.session_state.get("last_task_id", "")))

if st.button("Load Trace / Report", use_container_width=True) and task_id:
    try:
        trace = _get_json(f"/api/tasks/{task_id}/trace", timeout=60)
        report = _get_json(f"/api/tasks/{task_id}/report", timeout=60)
    except Exception as exc:
        st.error(str(exc))
    else:
        summary = report.get("summary", {})
        total_cost = sum(step.get("cost_ms") or 0 for step in trace)

        st.subheader("Run Overview")
        metric_cols = st.columns(6)
        metric_cols[0].metric("Executor Steps", summary.get("executor_steps", 0))
        metric_cols[1].metric("Trace Events", summary.get("trace_events", len(trace)))
        metric_cols[2].metric("AI Depth", summary.get("agent_depth_score", 0))
        metric_cols[3].metric("Failed Events", summary.get("failed_events", 0))
        metric_cols[4].metric("Screenshots", summary.get("screenshot_count", 0))
        metric_cols[5].metric("Cost ms", summary.get("total_recorded_cost_ms", total_cost))

        tab_ai, tab_trace, tab_report, tab_stats = st.tabs(["AI Workbench", "Trace", "Report", "Stats"])

        with tab_ai:
            ai_cols = st.columns(2)
            with ai_cols[0]:
                _render_json_block("Task Blueprint", summary.get("ai_task_blueprint"))
                _render_json_block("Result Judgement", summary.get("ai_result_judgement"))
                _render_json_block("Answer Synthesis", summary.get("ai_answer_synthesis"))
            with ai_cols[1]:
                _render_json_block("Action Policy Checks", summary.get("ai_action_policies"))
                _render_json_block("Step Critic Assessments", summary.get("ai_step_assessments"))
                _render_json_block("Failure Reflections", summary.get("ai_failure_reflections"))

        with tab_trace:
            for step in trace:
                title = f"Step {step['step_index']} - {step['node_name']} - {step.get('action_type') or ''}"
                with st.expander(title, expanded=step["node_name"] in {"executor", "ai_action_policy", "ai_step_critic"}):
                    left, right = st.columns([2, 1])
                    with left:
                        st.json(
                            {
                                "action_input": step.get("action_input"),
                                "observation": step.get("observation"),
                                "success": bool(step.get("success")),
                                "error_message": step.get("error_message"),
                                "cost_ms": step.get("cost_ms"),
                            }
                        )
                    with right:
                        screenshot_path = step.get("screenshot_path")
                        if screenshot_path and Path(screenshot_path).exists():
                            st.image(screenshot_path, caption=Path(screenshot_path).name, use_container_width=True)

        with tab_report:
            markdown = report.get("markdown", "")
            st.download_button(
                "Download Markdown report",
                data=markdown,
                file_name=f"webtask-report-{task_id}.md",
                mime="text/markdown",
                use_container_width=True,
            )
            st.markdown(markdown)

        with tab_stats:
            stat_cols = st.columns(2)
            with stat_cols[0]:
                _render_json_block("Tool Counts", summary.get("tool_counts"))
                _render_json_block("Node Counts", summary.get("node_counts"))
                _render_json_block("Failure Counts", summary.get("failure_counts"))
            with stat_cols[1]:
                _render_json_block("AI Mode Counts", summary.get("ai_mode_counts"))
                _render_json_block("Agent Depth Signals", summary.get("agent_depth_signals"))
