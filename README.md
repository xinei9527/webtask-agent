# WebTask Agent

浏览器任务自动化与执行追踪系统 MVP。用户输入自然语言任务后，系统会按 `observe -> plan -> execute -> verify` 循环控制浏览器，并把每一步动作、观察、截图、耗时和错误写入 SQLite Trace。

## 当前能力

- 支持网页检索、表单填写、商品信息抽取三类 MVP 任务。
- 支持工具：`open_url`、`click`、`click_by_text`、`type_text`、`type_by_selector`、`type_by_label`、`press`、`extract_text`、`extract_links`、`screenshot`、`wait_for_text`、`scroll`、`finish`。
- 使用 LangGraph 编排 Agent 节点。
- 默认规则 Planner 可离线演示；配置 `OPENAI_API_KEY` 后可扩展为 LLM Planner。
- SQLite 保存 `task_run` 和 `agent_trace` 两张核心表。
- Streamlit 展示任务结果、步骤时间线和截图。

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

打开接口文档：

```text
http://localhost:8000/docs
```

## 运行一个任务

```bash
curl -X POST http://localhost:8000/api/tasks/run ^
  -H "Content-Type: application/json" ^
  -d "{\"task\":\"打开本地搜索页面，搜索 Spring AI 工具调用，提取前三条结果标题和链接\"}"
```

也可以试：

```text
打开本地测试表单页面，填写姓名李威、手机号18254130015并提交
打开本地商品列表页面，提取价格最低的商品名称
打开百度，搜索“Spring AI 工具调用”，提取前三条搜索结果标题和链接
```

## 启动 Streamlit

```bash
streamlit run frontend/streamlit_app.py
```

## Trace 查询

```bash
curl http://localhost:8000/api/tasks/1/trace
curl http://localhost:8000/api/tasks/1/result
```

Trace 截图保存在：

```text
static/screenshots/
```

数据库默认保存在：

```text
data/webtask_agent.db
```

## 评测

先启动 API，再运行：

```bash
python -m app.eval.runner --api-base http://localhost:8000
```

评测集在 `app/eval/cases.json`，当前包含 20 个本地稳定任务，输出任务成功率、平均步骤数、平均耗时和失败类型分布。

## Docker

```bash
docker build -t webtask-agent .
docker run --rm -p 8000:8000 webtask-agent
```
