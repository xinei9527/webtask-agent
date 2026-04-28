from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dependency is provided by uvicorn[standard]
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[1]

if load_dotenv:
    load_dotenv(ROOT_DIR / ".env", override=False)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    temperature: float
    timeout: int
    max_retries: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "model": self.model,
            "base_url_configured": bool(self.base_url),
            "temperature": self.temperature,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "api_key_env": "OPENAI_API_KEY" if self.configured else None,
        }


def get_llm_config() -> LLMConfig:
    return LLMConfig(
        provider=os.getenv("WEBTASK_LLM_PROVIDER", "openai-compatible"),
        model=os.getenv("OPENAI_MODEL") or os.getenv("WEBTASK_LLM_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("WEBTASK_OPENAI_BASE_URL"),
        temperature=_float_env("WEBTASK_LLM_TEMPERATURE", 0.0),
        timeout=_int_env("WEBTASK_LLM_TIMEOUT", 60),
        max_retries=_int_env("WEBTASK_LLM_MAX_RETRIES", 2),
    )


def get_runtime_config() -> dict[str, Any]:
    return {
        "planner_default": os.getenv("WEBTASK_PLANNER", "hybrid"),
        "headless_default": os.getenv("WEBTASK_HEADLESS", "true"),
        "llm": get_llm_config().public_dict(),
    }
