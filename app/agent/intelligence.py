from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_llm_config


AiMode = Literal["llm", "heuristic"]


class TaskBlueprint(BaseModel):
    ai_mode: AiMode
    task_type: str
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ActionScore(BaseModel):
    ai_mode: AiMode
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["low", "medium", "high"]
    expected_effect: str
    risk_reasons: list[str] = Field(default_factory=list)
    fallback_action_hint: str | None = None


class StepAssessment(BaseModel):
    ai_mode: AiMode
    progress_status: Literal["on_track", "needs_replan", "blocked", "ready_to_finish"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    next_focus: str | None = None
    risk_flags: list[str] = Field(default_factory=list)


class ResultJudgement(BaseModel):
    ai_mode: AiMode
    passed: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str
    missing_items: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None


class FailureReflection(BaseModel):
    ai_mode: AiMode
    failure_type: str
    likely_cause: str
    recovery_strategies: list[str] = Field(default_factory=list)
    next_action_hint: str | None = None
    confidence: float = Field(ge=0, le=1)


class AnswerSynthesis(BaseModel):
    ai_mode: AiMode
    answer: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _task_type(user_task: str) -> str:
    if _contains_any(user_task, ("搜索", "检索", "百度", "search")):
        return "web_search"
    if _contains_any(user_task, ("表单", "填写", "手机号", "提交", "form")):
        return "form_fill"
    if _contains_any(user_task, ("提取", "抽取", "商品", "价格", "extract")):
        return "information_extraction"
    return "general_browser_task"


def re_match_numbered_result(line: str) -> bool:
    return bool(re.match(r"^\s*\d+[\.\)、)]\s+", line))


def _fallback_blueprint(user_task: str) -> TaskBlueprint:
    task_type = _task_type(user_task)
    templates: dict[str, dict[str, list[str] | str]] = {
        "web_search": {
            "goal": "Complete a search workflow and extract the requested result titles and links.",
            "success_criteria": ["target page opened", "query submitted", "requested search results extracted"],
            "plan_steps": ["open search page", "type query", "submit search", "extract result links", "return answer"],
            "suggested_tools": ["open_url", "type_text", "press", "extract_links", "finish"],
            "risks": ["real search pages may change", "result area may require waiting"],
        },
        "form_fill": {
            "goal": "Fill the requested form fields and verify the submit result.",
            "success_criteria": ["fields filled", "submit action completed", "success message observed"],
            "plan_steps": ["open form page", "locate fields", "fill fields", "submit", "read result"],
            "suggested_tools": ["open_url", "type_by_label", "click", "extract_text", "finish"],
            "risks": ["labels may differ", "submit result may appear asynchronously"],
        },
        "information_extraction": {
            "goal": "Extract the requested information from the target page.",
            "success_criteria": ["page content read", "target fields identified", "answer satisfies user condition"],
            "plan_steps": ["open page", "observe structure", "extract text or table", "filter result", "return answer"],
            "suggested_tools": ["open_url", "extract_text", "extract_table", "finish"],
            "risks": ["content may be paginated", "field formats may vary"],
        },
        "general_browser_task": {
            "goal": "Operate the browser according to the user's goal and return a verifiable answer.",
            "success_criteria": ["user goal completed", "final answer has supporting evidence"],
            "plan_steps": ["open target", "observe actionable elements", "choose action", "extract or verify result", "return answer"],
            "suggested_tools": ["open_url", "click", "type_text", "wait", "extract_text", "finish"],
            "risks": ["generic tasks require an LLM planner", "complex sites may need more steps"],
        },
    }
    template = templates[task_type]
    return TaskBlueprint(ai_mode="heuristic", task_type=task_type, **template)  # type: ignore[arg-type]


def _fallback_action_score(action: dict[str, Any], observation: dict[str, Any] | None) -> ActionScore:
    tool = action.get("tool", "unknown")
    args = action.get("args") or {}
    url = (observation or {}).get("url", "")

    if tool == "finish" and not str(args.get("answer", "")).strip():
        return ActionScore(
            ai_mode="heuristic",
            confidence=0.38,
            risk_level="high",
            expected_effect="Stop the task, but the answer is empty.",
            risk_reasons=["finish action has no answer"],
            fallback_action_hint="extract_text or extract_links before finish",
        )

    if tool in {"click", "click_by_text", "type_text", "type_by_selector", "type_by_label"}:
        return ActionScore(
            ai_mode="heuristic",
            confidence=0.76,
            risk_level="medium",
            expected_effect=f"Use {tool} on the current page.",
            risk_reasons=["element locator can fail if the page structure changed"],
            fallback_action_hint="re-observe the page and use actionable_elements selectors if it fails",
        )

    return ActionScore(
        ai_mode="heuristic",
        confidence=0.82,
        risk_level="low",
        expected_effect=f"Run {tool} while currently at {url or 'unknown URL'}.",
        risk_reasons=[],
        fallback_action_hint=None,
    )


def _fallback_step_assessment(action: dict[str, Any], result: dict[str, Any]) -> StepAssessment:
    tool = action.get("tool", "unknown")
    if not result.get("success"):
        return StepAssessment(
            ai_mode="heuristic",
            progress_status="blocked",
            confidence=0.82,
            evidence=[str(result.get("error") or "tool execution failed")],
            next_focus="repair the locator, wait for page readiness, or choose a different tool",
            risk_flags=["tool_failure"],
        )

    output = result.get("output")
    if tool == "finish":
        return StepAssessment(
            ai_mode="heuristic",
            progress_status="ready_to_finish",
            confidence=0.86,
            evidence=["finish action returned a final answer"],
            next_focus=None,
            risk_flags=[],
        )

    if tool in {"extract_text", "extract_links", "extract_table"} and output:
        return StepAssessment(
            ai_mode="heuristic",
            progress_status="ready_to_finish",
            confidence=0.72,
            evidence=[f"{tool} produced observable data"],
            next_focus="decide whether the extracted data is enough to answer",
            risk_flags=[],
        )

    return StepAssessment(
        ai_mode="heuristic",
        progress_status="on_track",
        confidence=0.7,
        evidence=[f"{tool} executed successfully"],
        next_focus="observe the updated page and choose the next action",
        risk_flags=[],
    )


def _fallback_judgement(user_task: str, final_result: str | None, error: str | None) -> ResultJudgement:
    if error:
        return ResultJudgement(
            ai_mode="heuristic",
            passed=False,
            confidence=0.9,
            rationale="The run returned an execution error.",
            missing_items=[error],
            suggested_next_action="Inspect the failed trace event and adjust locator, wait, or planner strategy.",
        )

    answer = (final_result or "").strip()
    if not answer:
        return ResultJudgement(
            ai_mode="heuristic",
            passed=False,
            confidence=0.75,
            rationale="No final answer was produced.",
            missing_items=["final_result"],
            suggested_next_action="Continue observing the page and extract the result before finishing.",
        )

    task_type = _task_type(user_task)
    missing_items: list[str] = []
    if task_type == "web_search":
        numbered_lines = [line for line in answer.splitlines() if re_match_numbered_result(line)]
        if ("前三" in user_task or "3" in user_task) and len(numbered_lines) < 3:
            missing_items.append("three search results")
        if "链接" in user_task and "http" not in answer.lower():
            missing_items.append("result links")
    elif task_type == "form_fill":
        if "提交成功" not in answer and "success" not in answer.lower():
            missing_items.append("submit success message")
    elif task_type == "information_extraction":
        if "价格" in user_task and not any(char.isdigit() for char in answer):
            missing_items.append("numeric price")

    if not missing_items:
        return ResultJudgement(
            ai_mode="heuristic",
            passed=True,
            confidence=0.78,
            rationale=f"Heuristic checks passed for {task_type}.",
            missing_items=[],
            suggested_next_action=None,
        )

    return ResultJudgement(
        ai_mode="heuristic",
        passed=False,
        confidence=0.82,
        rationale=f"Heuristic checks found missing evidence for {task_type}.",
        missing_items=missing_items,
        suggested_next_action="Extract or synthesize the missing evidence before finishing.",
    )


def _fallback_reflection(action: dict[str, Any], error: str, observation: dict[str, Any] | None) -> FailureReflection:
    error_lower = error.lower()
    tool = action.get("tool", "unknown")
    if "timeout" in error_lower or "timed out" in error_lower:
        failure_type = "page_timeout"
        strategies = ["wait for page stability", "use wait_for_text on a key phrase", "observe again before choosing the next action"]
    elif "not found" in error_lower or "locator" in error_lower:
        failure_type = "element_locator_error"
        strategies = ["use a selector from actionable_elements", "try visible text, label, or placeholder", "scroll and observe again"]
    elif "strict mode" in error_lower:
        failure_type = "ambiguous_locator"
        strategies = ["use a more specific selector", "target the first visible matching element", "extract candidate elements before acting"]
    else:
        failure_type = "execution_error"
        strategies = ["observe the page again", "try a different tool or locator strategy", "wait briefly and retry if the page is still changing"]

    url = (observation or {}).get("url", "")
    return FailureReflection(
        ai_mode="heuristic",
        failure_type=failure_type,
        likely_cause=f"{tool} failed; the current page or target element may differ from the expected state. URL: {url}",
        recovery_strategies=strategies,
        next_action_hint=strategies[0] if strategies else None,
        confidence=0.74,
    )


def _fallback_answer_synthesis(
    final_result: str | None,
    error: str | None,
    judgement: ResultJudgement,
    history: list[dict[str, Any]],
) -> AnswerSynthesis:
    if error:
        return AnswerSynthesis(
            ai_mode="heuristic",
            answer=f"任务失败：{error}",
            confidence=0.9,
            evidence=["execution error"],
        )

    answer = (final_result or "").strip()
    if len(answer) > 1800:
        answer = answer[:1800] + "..."

    evidence = []
    for item in history[-5:]:
        if item.get("success") and item.get("tool"):
            evidence.append(f"{item.get('tool')} succeeded")

    return AnswerSynthesis(
        ai_mode="heuristic",
        answer=answer or "任务结束，但没有生成最终结果。",
        confidence=judgement.confidence,
        evidence=evidence,
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


async def score_action(
    user_task: str,
    task_blueprint: dict[str, Any] | None,
    observation: dict[str, Any] | None,
    action: dict[str, Any],
    history: list[dict[str, Any]],
    recovery_notes: list[dict[str, Any]],
) -> ActionScore:
    system_prompt = """
You are an AI action policy checker for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Given the task, page observation, proposed action, and recent history, score whether the action is aligned.
Return: confidence, risk_level (low/medium/high), expected_effect, risk_reasons, fallback_action_hint.
"""
    try:
        data = await _call_json_model(
            system_prompt,
            {
                "user_task": user_task,
                "task_blueprint": task_blueprint,
                "observation": observation,
                "proposed_action": action,
                "recent_history": history[-6:],
                "recovery_notes": recovery_notes[-3:],
            },
        )
        data["ai_mode"] = "llm"
        return ActionScore.model_validate(data)
    except Exception:
        return _fallback_action_score(action, observation)


async def assess_step(
    user_task: str,
    task_blueprint: dict[str, Any] | None,
    action: dict[str, Any],
    result: dict[str, Any],
    observation: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> StepAssessment:
    system_prompt = """
You are an AI step critic for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Assess whether the latest action moved the task toward completion.
Return: progress_status (on_track/needs_replan/blocked/ready_to_finish), confidence, evidence, next_focus, risk_flags.
"""
    try:
        data = await _call_json_model(
            system_prompt,
            {
                "user_task": user_task,
                "task_blueprint": task_blueprint,
                "latest_action": action,
                "latest_result": result,
                "observation_before_action": observation,
                "recent_history": history[-6:],
            },
        )
        data["ai_mode"] = "llm"
        return StepAssessment.model_validate(data)
    except Exception:
        return _fallback_step_assessment(action, result)


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


async def synthesize_answer(
    user_task: str,
    final_result: str | None,
    error: str | None,
    judgement: ResultJudgement,
    history: list[dict[str, Any]],
) -> AnswerSynthesis:
    system_prompt = """
You are an AI answer synthesizer for a browser automation agent.
Return JSON only. Do not include hidden chain-of-thought.
Generate a concise user-facing final answer using the final result and trace evidence.
Return: answer, confidence, evidence.
Do not invent facts that are not present in the trace.
"""
    try:
        data = await _call_json_model(
            system_prompt,
            {
                "user_task": user_task,
                "final_result": final_result,
                "error": error,
                "result_judgement": judgement.model_dump(),
                "recent_history": history[-10:],
            },
        )
        data["ai_mode"] = "llm"
        return AnswerSynthesis.model_validate(data)
    except Exception:
        return _fallback_answer_synthesis(final_result, error, judgement, history)
