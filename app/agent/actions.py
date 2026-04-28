from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


PlannerMode = Literal["rule", "llm", "hybrid"]

ToolName = Literal[
    "open_url",
    "click",
    "click_by_text",
    "type_text",
    "type_by_selector",
    "type_by_label",
    "press",
    "wait_for_text",
    "extract_text",
    "extract_links",
    "scroll",
    "screenshot",
    "finish",
]


REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "open_url": ("url",),
    "click": ("selector_or_text",),
    "click_by_text": ("text",),
    "type_text": ("selector_or_text", "text"),
    "type_by_selector": ("selector", "value"),
    "type_by_label": ("label", "value"),
    "press": ("key",),
    "wait_for_text": ("text",),
    "extract_text": (),
    "extract_links": (),
    "scroll": (),
    "screenshot": ("path",),
    "finish": ("answer",),
}


class AgentAction(BaseModel):
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_common_arg_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        tool = data.get("tool")
        args = dict(data.get("args") or {})

        if tool == "open_url" and "url" not in args and "target" in args:
            args["url"] = args["target"]
        if tool == "click" and "selector_or_text" not in args:
            args["selector_or_text"] = args.get("text") or args.get("selector")
        if tool == "click_by_text" and "text" not in args and "selector_or_text" in args:
            args["text"] = args["selector_or_text"]
        if tool == "type_text":
            if "selector_or_text" not in args:
                args["selector_or_text"] = args.get("selector") or args.get("label")
            if "text" not in args and "value" in args:
                args["text"] = args["value"]
        if tool in {"type_by_selector", "type_by_label"} and "value" not in args and "text" in args:
            args["value"] = args["text"]

        data["args"] = args
        return data

    @model_validator(mode="after")
    def validate_required_args(self) -> "AgentAction":
        missing = [key for key in REQUIRED_ARGS[self.tool] if not self.args.get(key)]
        if missing:
            raise ValueError(f"{self.tool} missing required args: {', '.join(missing)}")
        return self


def make_action(tool: ToolName, args: dict[str, Any] | None = None, reason: str = "") -> dict[str, Any]:
    return AgentAction(tool=tool, args=args or {}, reason=reason).model_dump()


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    return AgentAction.model_validate(action).model_dump()
