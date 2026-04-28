from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st


API_BASE = os.getenv("WEBTASK_API_BASE", "http://localhost:8000")

st.set_page_config(page_title="WebTask Agent", layout="wide")
st.title("WebTask Agent")

default_task = "打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接"
task = st.text_area("输入浏览器任务", default_task, height=110)

col_run, col_headless, col_steps = st.columns([1, 1, 1])
with col_headless:
    headless = st.toggle("Headless", value=True)
with col_steps:
    max_steps = st.number_input("最大步骤数", min_value=3, max_value=30, value=12)

if col_run.button("运行任务", type="primary", use_container_width=True):
    with st.spinner("Agent 正在执行浏览器任务..."):
        resp = requests.post(
            f"{API_BASE}/api/tasks/run",
            json={"task": task, "headless": headless, "max_steps": int(max_steps)},
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
        st.caption(f"Task ID: {data['task_id']} | Status: {data['status']} | Elapsed: {data['elapsed_ms']} ms")
    else:
        st.error(resp.text)

task_id = st.text_input("查询 Trace Task ID", value=str(st.session_state.get("last_task_id", "")))

if st.button("查看 Trace", use_container_width=True) and task_id:
    trace_resp = requests.get(f"{API_BASE}/api/tasks/{task_id}/trace", timeout=60)
    if not trace_resp.ok:
        st.error(trace_resp.text)
    else:
        trace = trace_resp.json()
        total_cost = sum(step.get("cost_ms") or 0 for step in trace)
        st.subheader("执行步骤时间线")
        st.caption(f"Trace events: {len(trace)} | Recorded cost: {total_cost} ms")

        for step in trace:
            title = f"Step {step['step_index']} · {step['node_name']} · {step.get('action_type') or ''}"
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
