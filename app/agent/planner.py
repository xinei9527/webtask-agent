from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.agent.actions import PlannerMode, make_action, validate_action
from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_llm_config


ROOT_DIR = Path(__file__).resolve().parents[2]
PAGES_DIR = ROOT_DIR / "static" / "pages"
LLM_PARSE_RETRIES = 3


def _page_uri(name: str) -> str:
    return (PAGES_DIR / name).resolve().as_uri()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _extract_url(task: str) -> str | None:
    match = re.search(r"(https?://[^\s，。；,]+|file://[^\s，。；,]+)", task)
    return match.group(1) if match else None


def _extract_search_query(task: str) -> str:
    patterns = [
        r"(?:搜索|检索|search)\s*[“\"'「『]?([^”\"'」』，。；,\n]+)",
        r"(?:query|keyword)\s*[:：]\s*([^，。；,\n]+)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, task, flags=re.IGNORECASE):
            query = match.group(1).strip(" “”\"'「」『』")
            if query and query not in {"页面", "网页", "结果"} and not query.endswith("页面"):
                candidates.append(query)
    if candidates:
        return candidates[-1]
    return "Spring AI 工具调用"


def _extract_name(task: str) -> str:
    match = re.search(r"姓名\s*([\u4e00-\u9fa5A-Za-z]{2,20})", task)
    return match.group(1) if match else "测试用户"


def _extract_phone(task: str) -> str:
    match = re.search(r"(1[3-9]\d{9})", task)
    return match.group(1) if match else "13000000000"


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
    rows: list[tuple[str, float]] = []
    for line in text.splitlines():
        match = re.search(r"(.+?)[：:]\s*(\d+(?:\.\d+)?)\s*元", line.strip())
        if match:
            name = match.group(1).strip()
            rows.append((name, float(match.group(2))))

    if not rows:
        return text[:1200] if text else "没有提取到商品信息。"

    name, price = min(rows, key=lambda item: item[1])
    price_text = str(int(price)) if price.is_integer() else str(price)
    return f"价格最低的商品是：{name}，价格 {price_text} 元。"


class RulePlanner:
    def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        if _contains_any(task, ("表单", "填写", "手机号", "提交", "form")):
            return self._form_action(state)
        if _contains_any(task, ("商品", "价格最低", "产品", "最便宜", "extract")):
            return self._product_action(state)
        if _contains_any(task, ("搜索", "检索", "百度", "search")):
            return self._search_action(state)
        return self._generic_action(state)

    def _search_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        query = _extract_search_query(task)
        use_local = _contains_any(task, ("本地", "测试搜索", "search.html"))
        url = _extract_url(task) or (_page_uri("search.html") if use_local else "https://www.baidu.com")
        selector = "#q" if use_local else "input[name='wd']"
        link_selector = "#results a" if use_local else "h3 a, .result a"

        if not _has_tool(state, "open_url"):
            return make_action("open_url", {"url": url}, "Open the search page.")
        if not _has_tool(state, "type_by_selector"):
            return make_action("type_by_selector", {"selector": selector, "value": query}, "Type the search query.")
        if not _has_tool(state, "press"):
            return make_action("press", {"key": "Enter"}, "Submit the search.")
        if not _has_tool(state, "extract_links"):
            return make_action("extract_links", {"selector": link_selector, "limit": 10}, "Extract result titles and links.")
        return make_action("finish", {"answer": _format_links(_last_output(state), limit=3)}, "Return the first three results.")

    def _form_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task) or _page_uri("form.html")
        name = _extract_name(task)
        phone = _extract_phone(task)

        if not _has_tool(state, "open_url"):
            return make_action("open_url", {"url": url}, "Open the form page.")
        if not _has_action(state, "type_by_label", "label", "姓名"):
            return make_action("type_by_label", {"label": "姓名", "value": name}, "Fill the name field.")
        if not _has_action(state, "type_by_label", "label", "手机号"):
            return make_action("type_by_label", {"label": "手机号", "value": phone}, "Fill the phone field.")
        if not _has_tool(state, "click_by_text"):
            return make_action("click_by_text", {"text": "提交"}, "Submit the form.")
        if not _has_tool(state, "extract_text"):
            return make_action("extract_text", {"selector": "#result"}, "Read the submit result.")
        return make_action("finish", {"answer": str(_last_output(state) or "表单流程已完成。")}, "Return the form result.")

    def _product_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task) or _page_uri("products.html")

        if not _has_tool(state, "open_url"):
            return make_action("open_url", {"url": url}, "Open the product list page.")
        if not _has_tool(state, "extract_text"):
            return make_action("extract_text", {"selector": "#products"}, "Extract product list text.")
        return make_action(
            "finish",
            {"answer": _lowest_product_from_text(str(_last_output(state) or ""))},
            "Compute the lowest price product.",
        )

    def _generic_action(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state["user_task"]
        url = _extract_url(task)
        if url and not _has_tool(state, "open_url"):
            return make_action("open_url", {"url": url}, "Open the URL mentioned by the user.")
        if url and not _has_tool(state, "extract_text"):
            return make_action("extract_text", {"selector": "body"}, "Extract visible page text.")
        if _has_tool(state, "extract_text"):
            return make_action("finish", {"answer": str(_last_output(state) or "")[:1200]}, "Return extracted text.")
        return make_action(
            "finish",
            {
                "answer": (
                    "当前未配置大模型。通用浏览器 Agent 需要配置 OPENAI_API_KEY；"
                    "未配置时仅支持搜索、表单填写和商品信息抽取等规则兜底任务。"
                )
            },
            "No LLM is configured and the task does not match the rule planner.",
        )


class LLMPlanner:
    def __init__(self) -> None:
        config = get_llm_config()
        if not config.configured:
            raise RuntimeError("LLM planner requires OPENAI_API_KEY.")

        from langchain_openai import ChatOpenAI

        self.config = config
        self.model = ChatOpenAI(
            model=config.model,
            temperature=config.temperature,
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    async def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "user_task": state.get("user_task"),
            "task_blueprint": state.get("task_blueprint"),
            "observation": state.get("observation"),
            "history": state.get("history", [])[-8:],
            "recovery_notes": state.get("recovery_notes", [])[-3:],
            "step_assessments": state.get("step_assessments", [])[-3:],
            "last_error": state.get("error"),
            "current_step": state.get("current_step"),
            "max_steps": state.get("max_steps"),
        }

        validation_error = ""
        for attempt in range(LLM_PARSE_RETRIES):
            response = await self.model.ainvoke(
                [
                    ("system", SYSTEM_PROMPT),
                    (
                        "user",
                        json.dumps(
                            {
                                "task_context": payload,
                                "retry_instruction": validation_error,
                                "attempt": attempt + 1,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                ]
            )
            raw = str(response.content)
            try:
                return parse_action_json(raw)
            except Exception as exc:
                validation_error = (
                    "The previous output could not be executed. Return one valid JSON object only. "
                    f"Validation error: {exc}. Raw output: {raw[:800]}"
                )

        raise ValueError(f"LLM planner failed to produce a valid action after {LLM_PARSE_RETRIES} attempts.")


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("Planner output does not contain a JSON object.")


def parse_action_json(raw: str) -> dict[str, Any]:
    action = json.loads(_extract_json_object(raw))
    if not isinstance(action, dict):
        raise ValueError("Planner output must be a JSON object.")
    return validate_action(action)


class HybridPlanner:
    def __init__(self, mode: PlannerMode = "hybrid") -> None:
        self.mode = mode
        self.rule_planner = RulePlanner()
        self.llm_planner: LLMPlanner | None = None

        if mode in {"llm", "hybrid"} and get_llm_config().configured:
            self.llm_planner = LLMPlanner()
        elif mode == "llm":
            raise RuntimeError("planner_mode='llm' requires OPENAI_API_KEY.")

    async def next_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "rule":
            return self.rule_planner.next_action(state)

        if self.mode == "llm":
            if self.llm_planner is None:
                raise RuntimeError("LLM planner is not available.")
            return await self.llm_planner.next_action(state)

        if self.llm_planner is not None:
            try:
                return await self.llm_planner.next_action(state)
            except Exception as exc:
                fallback = self.rule_planner.next_action(state)
                fallback["reason"] = f"LLM planner failed, falling back to rule planner: {exc}"
                return fallback

        return self.rule_planner.next_action(state)
