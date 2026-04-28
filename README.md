# WebTask Agent

WebTask Agent is a browser task automation and execution tracing system. A user enters a natural-language browser task, and the system runs an `observe -> plan -> policy check -> execute -> critique -> verify -> synthesize` loop to control Playwright, record every action, and produce a replayable trace report.

## What It Does

- Runs browser tasks from natural language: search, form filling, and information extraction.
- Uses Playwright browser tools for opening pages, clicking, typing, selecting, scrolling, extracting text/links/tables, screenshots, and page state inspection.
- Uses LangGraph to orchestrate page observation, planner decisions, tool execution, verification, and AI cognition nodes.
- Stores task runs and Agent Trace events in SQLite.
- Generates structured trace reports with screenshots, tool inputs/outputs, cost, errors, failure types, and AI assessments.
- Provides a FastAPI backend and a Streamlit demo console.
- Includes local demo pages and a small evaluation set for stable demonstrations.

## AI Intelligence Layer

The project is not only a browser automation script. It includes an explicit AI cognition layer:

```text
Task Blueprint        -> task type, goal, success criteria, plan steps, risks
LLM-first Planner     -> model chooses the next browser tool when configured
Action Policy Check   -> scores each proposed action before execution
Step Critic           -> checks whether each action moved the task forward
Failure Reflection    -> classifies failures and suggests recovery strategies
Result Judgement      -> verifies whether the final answer satisfies the task
Answer Synthesizer    -> turns raw extraction results into a user-facing answer
AI Trace              -> writes all cognition outputs into the trace/report
```

Without an API key, these modules run with deterministic heuristic fallbacks so the demo remains runnable. With `OPENAI_API_KEY`, `hybrid` and `llm` modes use an OpenAI-compatible chat model.

## Tech Stack

```text
Python / FastAPI / Playwright / LangGraph / SQLite / Streamlit / Docker
```

## Project Structure

```text
app/
  agent/       # LangGraph workflow, planners, action schema, AI cognition, verifier
  browser/     # Playwright session, tools, page observer
  db/          # SQLite schema and data access
  eval/        # evaluation cases and runner
  trace/       # trace recorder, analyzer, report builder
frontend/      # Streamlit demo console
static/pages/  # local demo pages
```

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Configure LLM

Copy the example environment file:

```bash
copy .env.example .env
```

Example `.env`:

```text
WEBTASK_PLANNER=hybrid
OPENAI_API_KEY=<your-openai-api-key>
OPENAI_MODEL=gpt-4o-mini
```

For other OpenAI-compatible services:

```text
OPENAI_BASE_URL=<openai-compatible-base-url>
```

The API only exposes whether the key is configured. It never returns the key value.

## Run API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docs:

```text
http://localhost:8000/docs
```

## Run Streamlit

```bash
streamlit run frontend/streamlit_app.py
```

Demo console:

```text
http://localhost:8501
```

## API

```text
GET  /api/health
GET  /api/config
POST /api/tasks/run
GET  /api/tasks
GET  /api/tasks/{task_id}/trace
GET  /api/tasks/{task_id}/result
GET  /api/tasks/{task_id}/report
```

Example:

```bash
curl -X POST http://localhost:8000/api/tasks/run ^
  -H "Content-Type: application/json" ^
  -d "{\"task\":\"打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接\",\"planner_mode\":\"hybrid\"}"
```

Useful demo tasks:

```text
打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接
打开本地测试表单页面，填写姓名测试用户甲、手机号13000000001并提交
打开本地商品列表页面，提取价格最低的商品名称
```

## Planner Modes

```text
rule   -> deterministic planner for stable demos and evaluation
llm    -> model-only planner; requires OPENAI_API_KEY
hybrid -> default; use LLM first, fallback to rules when unavailable
```

All planner outputs pass through a Pydantic `AgentAction` schema. The agent only executes whitelisted tools and validates required arguments before execution.

## Tool Set

```text
open_url / click / click_by_text / type_text / type_by_selector / type_by_label
select_option / hover / press / wait / wait_for_text / scroll / go_back
extract_text / extract_links / extract_table / current_page / screenshot / finish
```

## Trace Report

The report includes:

```text
task status
final answer
executor steps
trace event count
tool/node/failure distributions
screenshots
AI task blueprint
AI action policy checks
AI step critic assessments
AI failure reflections
AI result judgement
AI answer synthesis
agent depth score
Markdown export
```

## Evaluation

Start the API first, then run:

```bash
python -m app.eval.runner --api-base http://localhost:8000
```

Metrics:

```text
success rate
average executor steps
average elapsed time
failure type distribution
AI judgement pass/confidence
```

## Docker

```bash
docker build -t webtask-agent .
docker run --rm -p 8000:8000 webtask-agent
```

## Resume Highlights

- Designed a controlled browser Agent workflow with LangGraph, separating observation, planning, action policy, execution, critique, verification, and answer synthesis.
- Implemented a structured page observer that extracts title, URL, visible text, links, buttons, inputs, and actionable elements instead of sending full DOM context.
- Added a whitelisted browser tool layer and schema-validated tool calls to reduce model hallucination and execution risk.
- Built an Agent Trace system that records every action input/output, screenshots, latency, errors, AI assessments, and final report data.
- Added failure classification, retry, reflection, and recovery hints for locator failures, timeouts, ambiguous selectors, and result gaps.
- Built local evaluation tasks and a Streamlit trace console to demonstrate success rate, average steps, failure distribution, and AI cognition timeline.
