from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st


API_BASE = os.getenv("WEBTASK_API_BASE", "http://localhost:8000")

st.set_page_config(page_title="WebTask Agent", layout="wide")
st.title("WebTask Agent")

try:
    config_resp = requests.get(f"{API_BASE}/api/config", timeout=10)
    runtime_config = config_resp.json() if config_resp.ok else {}
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

default_task = "打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接"
task = st.text_area("输入浏览器任务", default_task, height=110)

col_run, col_headless, col_steps = st.columns([1, 1, 1])
with col_headless:
    headless = st.toggle("Headless", value=True)
with col_steps:
    max_steps = st.number_input("最大步骤数", min_value=3, max_value=30, value=12)

planner_mode = st.selectbox(
    "Planner",
    options=["hybrid", "rule", "llm"],
    index=0,
    help="hybrid 会让本地稳定任务走规则，非 MVP 任务在配置 OPENAI_API_KEY 后走大模型。",
)

if col_run.button("运行任务", type="primary", use_container_width=True):
    with st.spinner("Agent 正在执行浏览器任务..."):
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
        st.subheader("最终结果")
        if data.get("error_message"):
            st.error(data["error_message"])
        else:
            st.success(data.get("final_result") or "任务完成")
        st.caption(
            f"Task ID: {data['task_id']} | Status: {data['status']} | "
            f"Planner: {data.get('planner_mode')} | Elapsed: {data['elapsed_ms']} ms"
        )
    else:
        st.error(resp.text)

task_id = st.text_input("查询 Trace Task ID", value=str(st.session_state.get("last_task_id", "")))

if st.button("查看 Trace / 报告", use_container_width=True) and task_id:
    trace_resp = requests.get(f"{API_BASE}/api/tasks/{task_id}/trace", timeout=60)
    report_resp = requests.get(f"{API_BASE}/api/tasks/{task_id}/report", timeout=60)
    if not trace_resp.ok:
        st.error(trace_resp.text)
    elif not report_resp.ok:
        st.error(report_resp.text)
    else:
        trace = trace_resp.json()
        report = report_resp.json()
        summary = report.get("summary", {})
        total_cost = sum(step.get("cost_ms") or 0 for step in trace)

        st.subheader("执行概览")
        metric_cols = st.columns(5)
        metric_cols[0].metric("Executor Steps", summary.get("executor_steps", 0))
        metric_cols[1].metric("Trace Events", summary.get("trace_events", len(trace)))
        metric_cols[2].metric("Failed Events", summary.get("failed_events", 0))
        metric_cols[3].metric("Screenshots", summary.get("screenshot_count", 0))
        metric_cols[4].metric("Cost ms", summary.get("total_recorded_cost_ms", total_cost))

        tab_trace, tab_report, tab_stats = st.tabs(["Trace", "Report", "Stats"])

        with tab_trace:
            for step in trace:
                title = f"Step {step['step_index']} - {step['node_name']} - {step.get('action_type') or ''}"
                with st.expander(title, expanded=step["node_name"] == "executor"):
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
                "下载 Markdown 报告",
                data=markdown,
                file_name=f"webtask-report-{task_id}.md",
                mime="text/markdown",
                use_container_width=True,
            )
            st.markdown(markdown)

        with tab_stats:
            st.write("Tool Counts")
            st.json(summary.get("tool_counts", {}))
            st.write("Node Counts")
            st.json(summary.get("node_counts", {}))
            st.write("Failure Counts")
            st.json(summary.get("failure_counts", {}))
