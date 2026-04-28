from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT


ROOT_DIR = Path(__file__).resolve().parents[2]
PAGES_DIR = ROOT_DIR / "static" / "pages"


def _page_uri(name: str) -> str:
    return (PAGES_DIR / name).resolve().as_uri()


def _extract_url(task: str) -> str | None:
    match = re.search(r"(https?://[^\s，。]+|file://[^\s，。]+)", task)
    return match.group(1) if match else None


def _extract_search_query(task: str) -> str:
    quoted_patterns = [
        r"搜索[“\"']([^”\"']+)[”\"']",
        r"检索[“\"']([^”\"']+)[”\"']",
    ]
    for pattern in quoted_patterns:
        match = re.search(pattern, task)
        if match:
            return match.group(1).strip()

    patterns = [
        r"搜索\s*([^，,。]+)",
        r"检索\s*([^，,。]+)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, task):
            query = match.group(1).strip()
            query = re.sub(r"^(一下|关键词)?", "", query).strip()
            if query and query not in {"页面", "网页", "结果"} and not query.endswith("页面"):
                candidates.append(query)
    if candidates:
        return candidates[-1]
    return "Spring AI 工具调用"


def _extract_name(task: str) -> str:
    match = re.search(r"姓名\s*([\u4e00-\u9fa5A-Za-z]{2,20})", task)
    return match.group(1) if match else "李威"


def _extract_phone(task: str) -> str:
    match = re.search(r"(1[3-9]\d{9})", task)
    return match.group(1) if match else "18254130015"


def _history(state: dict[str, Any]) -> list[dict[str, Any]]:
    return state.get("history") or []


def _last_output(state: dict[str, Any]) -> Any:
    history = _history(state)
    return history[-1].get("output") if history else None


def _has_tool(state: dict[str, Any], tool: str) -> bool:
    return any(item.get("tool") == tool and item.get("success") for item in _history(state))


def _has_action(state: dict[str, Any], tool: str, key: str, value: str) -> bool:
    for item in _history(state):
        args = item.get("args") or {}
        if item.get("tool") == tool and item.get("success") and args.get(key) == value:
            return True
    return False


def _format_links(output: Any, limit: int = 3) -> str:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return output[:1200]

    if not isinstance(output, list):
        return "未提取到链接。"

    blocked = {"百度一下", "百度首页", "新闻", "地图", "贴吧", "图片", "视频", "更多"}
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in output:
        text = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
        href = str(item.get("href", "")).strip() if isinstance(item, dict) else ""
        if not text or not href or text in blocked:
            continue
        key = f"{text}|{href}"
        if key in seen:
            continue
        seen.add(key)
        results.append({"text": text, "href": href})
        if len(results) >= limit:
            break

    if not results:
        return "未提取到有效搜索结果链接。"

    return "\n".join(
        f"{index}. {item['text']} - {item['href']}"
        for index, item in enumerate(results, start=1)
    )


def _lowest_product_from_text(text: str) -> str:
    rows = []
    for line in text.splitlines():
        match = re.search(r"(.+?)[：:]\s*(\d+(?:\.\d+)?)\s*元", line.strip())
        if match:
            rows.append((match.group(1).strip(), float(match.group(2))))

    if not rows:
        return text[:1200] if text else "没有提取到商品信息。"

    name, price = min(rows, key=lambda item: item[1])
    price_text = str(int(price)) if price.is_integer() else str(price)
    return f"价格最低的商品是：{name}，价格 {price_text} 元。"


class RulePlanner:
    def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        if any(keyword in task for keyword in ("表单", "填写", "手机号", "提交")):
            return self._form_action(state)
        if any(keyword in task for keyword in ("商品", "价格最低", "产品")):
            return self._product_action(state)
        if any(keyword in task for keyword in ("搜索", "检索", "百度")):
            return self._search_action(state)
        return self._generic_action(state)

    def _search_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        query = _extract_search_query(task)
        use_local = any(keyword in task for keyword in ("本地", "测试搜索", "search.html"))
        url = _extract_url(task) or (_page_uri("search.html") if use_local else "https://www.baidu.com")
        selector = "#q" if use_local else "input[name='wd']"
        link_selector = "#results a" if use_local else "h3 a, .result a"

        if not _has_tool(state, "open_url"):
            return {
                "tool": "open_url",
                "args": {"url": url},
                "reason": "打开搜索入口页面",
            }
        if not _has_tool(state, "type_by_selector"):
            return {
                "tool": "type_by_selector",
                "args": {"selector": selector, "value": query},
                "reason": "输入搜索关键词",
            }
        if not _has_tool(state, "press"):
            return {
                "tool": "press",
                "args": {"key": "Enter"},
                "reason": "提交搜索",
            }
        if not _has_tool(state, "extract_links"):
            return {
                "tool": "extract_links",
                "args": {"selector": link_selector, "limit": 10},
                "reason": "提取搜索结果标题和链接",
            }
        return {
            "tool": "finish",
            "args": {"answer": _format_links(_last_output(state), limit=3)},
            "reason": "已经提取到搜索结果",
        }

    def _form_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task) or _page_uri("form.html")
        name = _extract_name(task)
        phone = _extract_phone(task)

        if not _has_tool(state, "open_url"):
            return {
                "tool": "open_url",
                "args": {"url": url},
                "reason": "打开本地表单页面",
            }
        if not _has_action(state, "type_by_label", "label", "姓名"):
            return {
                "tool": "type_by_label",
                "args": {"label": "姓名", "value": name},
                "reason": "填写姓名字段",
            }
        if not _has_action(state, "type_by_label", "label", "手机号"):
            return {
                "tool": "type_by_label",
                "args": {"label": "手机号", "value": phone},
                "reason": "填写手机号字段",
            }
        if not _has_tool(state, "click_by_text"):
            return {
                "tool": "click_by_text",
                "args": {"text": "提交"},
                "reason": "提交表单",
            }
        if not _has_tool(state, "extract_text"):
            return {
                "tool": "extract_text",
                "args": {"selector": "#result"},
                "reason": "读取提交结果",
            }
        return {
            "tool": "finish",
            "args": {"answer": str(_last_output(state) or "表单流程已完成。")},
            "reason": "表单结果已经获取",
        }

    def _product_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task) or _page_uri("products.html")

        if not _has_tool(state, "open_url"):
            return {
                "tool": "open_url",
                "args": {"url": url},
                "reason": "打开商品列表页面",
            }
        if not _has_tool(state, "extract_text"):
            return {
                "tool": "extract_text",
                "args": {"selector": "#products"},
                "reason": "提取商品列表文本",
            }
        return {
            "tool": "finish",
            "args": {"answer": _lowest_product_from_text(str(_last_output(state) or ""))},
            "reason": "已经根据价格计算出最低价商品",
        }

    def _generic_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task)
        if url and not _has_tool(state, "open_url"):
            return {
                "tool": "open_url",
                "args": {"url": url},
                "reason": "打开任务中指定的网址",
            }
        if url and not _has_tool(state, "extract_text"):
            return {
                "tool": "extract_text",
                "args": {"selector": "body"},
                "reason": "提取页面正文",
            }
        if _has_tool(state, "extract_text"):
            return {
                "tool": "finish",
                "args": {"answer": str(_last_output(state) or "")[:1200]},
                "reason": "页面文本已经提取",
            }
        return {
            "tool": "finish",
            "args": {
                "answer": "当前 MVP 支持网页检索、表单填写和商品/信息抽取任务。请尝试描述这三类任务。"
            },
            "reason": "任务类型不在当前 MVP 支持范围内",
        }


class LLMPlanner:
    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI

        self.model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
        )

    async def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "user_task": state.get("user_task"),
            "observation": state.get("observation"),
            "history": state.get("history", [])[-6:],
            "last_error": state.get("error"),
        }
        response = await self.model.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("user", json.dumps(payload, ensure_ascii=False, default=str)),
            ]
        )
        return parse_action_json(response.content)


def parse_action_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    action = json.loads(text)
    if not isinstance(action, dict) or "tool" not in action:
        raise ValueError("Planner output must be a JSON object with a tool field.")
    action.setdefault("args", {})
    action.setdefault("reason", "")
    return action


class HybridPlanner:
    def __init__(self) -> None:
        self.rule_planner = RulePlanner()
        self.llm_planner = None
        if os.getenv("OPENAI_API_KEY"):
            try:
                self.llm_planner = LLMPlanner()
            except Exception:
                self.llm_planner = None

    async def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        known_task = any(
            keyword in task
            for keyword in ("搜索", "检索", "百度", "表单", "填写", "手机号", "提交", "商品", "价格最低", "产品")
        )
        if known_task or self.llm_planner is None:
            return self.rule_planner.next_action(state)
        return await self.llm_planner.next_action(state)
