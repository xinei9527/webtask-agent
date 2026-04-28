from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_llm_config


class TaskBlueprint(BaseModel):
    ai_mode: Literal["llm", "heuristic"]
    task_type: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ResultJudgement(BaseModel):
    ai_mode: Literal["llm", "heuristic"]
    passed: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str
    missing_items: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None


class FailureReflection(BaseModel):
    ai_mode: Literal["llm", "heuristic"]
    failure_type: str
    likely_cause: str
    recovery_strategies: list[str] = Field(default_factory=list)
    next_action_hint: str | None = None
    confidence: float = Field(ge=0, le=1)


def _is_search_task(task: str) -> bool:
    return any(keyword in task for keyword in ("搜索", "检索", "百度", "search"))


def _is_form_task(task: str) -> bool:
    return any(keyword in task for keyword in ("表单", "填写", "提交", "手机号", "form"))


def _is_extract_task(task: str) -> bool:
    return any(keyword in task for keyword in ("提取", "抽取", "商品", "价格", "extract"))


def _fallback_blueprint(user_task: str) -> TaskBlueprint:
    if _is_search_task(user_task):
        return TaskBlueprint(
            ai_mode="heuristic",
            task_type="web_search",
            goal="完成网页搜索并提取用户要求的搜索结果。",
            success_criteria=["页面已打开", "关键词已提交", "结果标题和链接已提取"],
            plan_steps=["打开搜索页面", "输入关键词", "提交搜索", "提取结果", "返回答案"],
            suggested_tools=["open_url", "type_text", "press", "extract_links", "finish"],
            risks=["真实搜索引擎页面结构可能变化", "结果区域可能需要等待加载"],
        )
    if _is_form_task(user_task):
        return TaskBlueprint(
            ai_mode="heuristic",
            task_type="form_fill",
            goal="根据用户描述填写表单并提交。",
            success_criteria=["字段填写完成", "提交动作完成", "页面出现提交结果"],
            plan_steps=["打开表单页面", "定位输入框", "填写字段", "点击提交", "读取结果"],
            suggested_tools=["open_url", "type_by_label", "click", "extract_text", "finish"],
            risks=["字段 label 可能不一致", "提交后可能需要等待结果文本"],
        )
    if _is_extract_task(user_task):
        return TaskBlueprint(
            ai_mode="heuristic",
            task_type="information_extraction",
            goal="打开目标页面并抽取满足条件的信息。",
            success_criteria=["页面内容已读取", "目标字段已识别", "输出满足用户条件"],
            plan_steps=["打开页面", "观察页面结构", "提取正文或表格", "计算或筛选结果", "返回答案"],
            suggested_tools=["open_url", "extract_text", "extract_table", "finish"],
            risks=["内容可能分页或需要滚动", "价格/字段格式可能不统一"],
        )
    return TaskBlueprint(
        ai_mode="heuristic",
        task_type="general_browser_task",
        goal="根据用户目标操作浏览器并返回结果。",
        success_criteria=["完成用户指定目标", "返回可验证的最终结果"],
        plan_steps=["打开目标页面", "观察可操作元素", "选择动作", "提取或校验结果", "返回答案"],
        suggested_tools=["open_url", "click", "type_text", "wait", "extract_text", "finish"],
        risks=["未配置大模型时泛化能力有限", "复杂网页可能需要更多步骤"],
    )


def _fallback_judgement(user_task: str, final_result: str | None, error: str | None) -> ResultJudgement:
    if error:
        return ResultJudgement(
            ai_mode="heuristic",
            passed=False,
            confidence=0.9,
            rationale="任务执行返回错误，判定未通过。",
            missing_items=[error],
            suggested_next_action="查看 Trace 中失败步骤并调整定位策略或增加等待。",
        )
    if final_result and final_result.strip():
        return ResultJudgement(
            ai_mode="heuristic",
            passed=True,
            confidence=0.72,
            rationale="任务产生了非空最终结果，启发式判定通过。",
            missing_items=[],
            suggested_next_action=None,
        )
    return ResultJudgement(
        ai_mode="heuristic",
        passed=False,
        confidence=0.75,
        rationale="没有最终结果，启发式判定未通过。",
        missing_items=["final_result"],
        suggested_next_action="继续观察页面并提取结果。",
    )


def _fallback_reflection(action: dict[str, Any], error: str, observation: dict[str, Any] | None) -> FailureReflection:
    error_lower = error.lower()
    tool = action.get("tool", "unknown")
    if "timeout" in error_lower:
        failure_type = "page_timeout"
        strategies = ["等待页面稳定后重试", "使用 wait_for_text 等待关键文本", "重新观察页面后再选择动作"]
    elif "not found" in error_lower or "locator" in error_lower:
        failure_type = "element_locator_error"
        strategies = ["改用 actionable_elements 中的 selector", "改用可见文本或 label 定位", "先滚动页面寻找目标元素"]
    elif "strict mode" in error_lower:
        failure_type = "ambiguous_locator"
        strategies = ["使用更具体的 selector", "选择 first/可见文本更精确的元素", "先提取页面元素列表再定位"]
    else:
        failure_type = "execution_error"
        strategies = ["重新 observe 页面", "换一种工具或定位策略", "必要时返回上一页或等待后重试"]

    url = (observation or {}).get("url", "")
    return FailureReflection(
        ai_mode="heuristic",
        failure_type=failure_type,
        likely_cause=f"{tool} 执行失败，当前页面或元素定位可能与预期不一致。URL: {url}",
        recovery_strategies=strategies,
        next_action_hint=strategies[0] if strategies else None,
        confidence=0.74,
    )


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start : end + 1]
    raise ValueError("No JSON object found in model output.")


async def _call_json_model(system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = get_llm_config()
    if not config.configured:
        raise RuntimeError("LLM is not configured.")

    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )
    response = await model.ainvoke(
        [
            ("system", system_prompt),
            ("user", json.dumps(payload, ensure_ascii=False, default=str)),
        ]
    )
    return json.loads(_extract_json_object(str(response.content)))


async def analyze_task(user_task: str) -> TaskBlueprint:
    system_prompt = """
You are an AI task analyst for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Analyze the user's browser task and produce:
task_type, goal, success_criteria, plan_steps, suggested_tools, risks.
Keep plan_steps concise and actionable.
"""
    try:
        data = await _call_json_model(system_prompt, {"user_task": user_task})
        data["ai_mode"] = "llm"
        return TaskBlueprint.model_validate(data)
    except Exception:
        return _fallback_blueprint(user_task)


async def judge_result(
    user_task: str,
    final_result: str | None,
    error: str | None,
    history: list[dict[str, Any]],
) -> ResultJudgement:
    system_prompt = """
You are an AI verifier for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Judge whether the final result satisfies the user task.
Return: passed, confidence, rationale, missing_items, suggested_next_action.
The rationale must be short and evidence-based.
"""
    try:
        data = await _call_json_model(
            system_prompt,
            {
                "user_task": user_task,
                "final_result": final_result,
                "error": error,
                "recent_history": history[-8:],
            },
        )
        data["ai_mode"] = "llm"
        return ResultJudgement.model_validate(data)
    except Exception:
        return _fallback_judgement(user_task, final_result, error)


async def reflect_failure(
    user_task: str,
    action: dict[str, Any],
    error: str,
    observation: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> FailureReflection:
    system_prompt = """
You are an AI failure analyst for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Analyze the failed browser action and return:
failure_type, likely_cause, recovery_strategies, next_action_hint, confidence.
Keep the advice concrete and based on the current observation/action/error.
"""
    try:
        data = await _call_json_model(
            system_prompt,
            {
                "user_task": user_task,
                "failed_action": action,
                "error": error,
                "observation": observation,
                "recent_history": history[-6:],
            },
        )
        data["ai_mode"] = "llm"
        return FailureReflection.model_validate(data)
    except Exception:
        return _fallback_reflection(action, error, observation)
