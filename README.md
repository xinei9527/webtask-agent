# WebTask Agent

浏览器任务自动化与执行追踪系统 MVP。用户输入自然语言网页任务后，系统会按照 `observe -> plan -> execute -> verify` 流程控制浏览器，并记录每一步动作、观察、截图、耗时和错误信息。

## 功能概览

- 支持网页检索、表单填写、信息抽取三类 MVP 任务。
- 基于 Playwright 封装浏览器工具，包括打开网页、点击、输入、提取文本、提取链接、截图和滚动。
- 基于 LangGraph 编排页面观察、动作选择、工具执行和结果校验流程。
- 基于 SQLite 保存任务运行记录和 Agent Trace。
- 支持失败重试、错误分类、Trace 查询和 Markdown 报告生成。
- 提供 FastAPI 接口和 Streamlit 演示页面。
- 内置本地测试页面和 20 条评测任务，便于稳定演示。

## 技术栈

```text
Python / FastAPI / Playwright / LangGraph / SQLite / Streamlit / Docker
```

## 目录结构

```text
app/
  agent/       # Agent 工作流、Planner、动作 schema、校验逻辑
  browser/     # Playwright 会话、浏览器工具、页面观察
  db/          # SQLite 初始化和访问
  eval/        # 评测集与评测脚本
  trace/       # Trace 记录、分析和报告生成
frontend/      # Streamlit 演示页面
static/pages/  # 本地测试页面
```

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## 启动 API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

接口文档：

```text
http://localhost:8000/docs
```

## 运行任务

```bash
curl -X POST http://localhost:8000/api/tasks/run ^
  -H "Content-Type: application/json" ^
  -d "{\"task\":\"打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接\",\"planner_mode\":\"hybrid\"}"
```

可以尝试的任务：

```text
打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接
打开本地测试表单页面，填写示例姓名和示例联系方式并提交
打开本地商品列表页面，提取价格最低的商品名称
```

## Planner 模式

项目支持三种 Planner：

```text
rule   ：只使用规则 Planner，适合稳定演示和评测。
llm    ：只使用大模型 Planner，需要配置 OPENAI_API_KEY。
hybrid ：默认模式。MVP 稳定任务走规则；未知任务在有 OPENAI_API_KEY 时走大模型。
```

环境变量示例：

```bash
set WEBTASK_PLANNER=hybrid
set OPENAI_API_KEY=<your-openai-api-key>
set OPENAI_MODEL=gpt-4o-mini
```

LLM Planner 的输出会经过 `AgentAction` Pydantic schema 校验，只允许白名单工具，并检查必要参数。模型输出 JSON 解析失败、工具名非法或参数缺失时，会自动要求模型重新输出合法动作，最多重试 3 次。

## Trace 和报告

查询 Trace：

```bash
curl http://localhost:8000/api/tasks/1/trace
```

查询结果：

```bash
curl http://localhost:8000/api/tasks/1/result
```

生成执行报告：

```bash
curl http://localhost:8000/api/tasks/1/report
```

报告包含：

```text
任务状态
最终结果
执行步骤数
Trace 事件数
工具调用分布
节点分布
失败类型分布
截图数量
执行时间线
Markdown 报告
```

## 启动 Streamlit

```bash
streamlit run frontend/streamlit_app.py
```

页面能力：

```text
提交自然语言任务
查看最终结果
查看执行概览指标
查看 Trace 时间线
查看截图
查看工具调用统计
下载 Markdown 报告
```

## 评测

先启动 API，再运行：

```bash
python -m app.eval.runner --api-base http://localhost:8000
```

评测维度：

```text
任务成功率
平均执行步数
平均耗时
失败类型分布
```

## Docker

```bash
docker build -t webtask-agent .
docker run --rm -p 8000:8000 webtask-agent
```

## 项目亮点

- 结构化页面观察：抽取页面标题、URL、文本摘要、链接、按钮、输入框和 `actionable_elements`，避免直接把完整 DOM 交给 Planner。
- 可控动作空间：所有 Planner 动作都经过 `AgentAction` schema 校验，降低大模型幻觉工具和参数错误风险。
- 可观测执行链路：观察、规划、执行、校验节点都会记录 Trace，便于复盘每一步行为。
- 失败分析报告：自动统计工具调用分布、节点分布、失败类型、截图数量和执行时间线。
- 稳定评测闭环：内置本地页面和小规模任务集，可稳定评估 Agent 的成功率、耗时和失败类型。
