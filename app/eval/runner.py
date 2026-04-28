from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests


CASES_PATH = Path(__file__).with_name("cases.json")


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def run_eval(api_base: str) -> dict[str, Any]:
    cases = load_cases()
    results = []
    failure_types: Counter[str] = Counter()
    total_steps = 0
    total_elapsed = 0

    for case in cases:
        started = time.time()
        try:
            resp = requests.post(
                f"{api_base}/api/tasks/run",
                json={"task": case["task"], "headless": True, "max_steps": 12},
                timeout=240,
            )
            resp.raise_for_status()
            data = resp.json()
            final_result = data.get("final_result") or ""
            keyword_ok = all(keyword in final_result for keyword in case["expected_keywords"])
            success = data.get("status") == "completed" and keyword_ok
            failure_type = None if success else (data.get("error_message") or "result_check_failed")
            if failure_type:
                failure_types[failure_type] += 1
            total_steps += int(data.get("steps") or 0)
            total_elapsed += int(data.get("elapsed_ms") or ((time.time() - started) * 1000))
            results.append(
                {
                    "id": case["id"],
                    "type": case["type"],
                    "success": success,
                    "task_id": data.get("task_id"),
                    "steps": data.get("steps"),
                    "elapsed_ms": data.get("elapsed_ms"),
                    "final_result": final_result,
                    "failure_type": failure_type,
                }
            )
        except Exception as exc:
            failure_types[type(exc).__name__] += 1
            total_elapsed += int((time.time() - started) * 1000)
            results.append(
                {
                    "id": case["id"],
                    "type": case["type"],
                    "success": False,
                    "task_id": None,
                    "steps": 0,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "final_result": "",
                    "failure_type": str(exc),
                }
            )

    success_count = sum(1 for item in results if item["success"])
    total = len(results)
    return {
        "total": total,
        "success_count": success_count,
        "success_rate": round(success_count / total, 4) if total else 0,
        "avg_steps": round(total_steps / total, 2) if total else 0,
        "avg_elapsed_ms": round(total_elapsed / total, 2) if total else 0,
        "failure_types": dict(failure_types),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://localhost:8000")
    args = parser.parse_args()
    report = run_eval(args.api_base.rstrip("/"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
