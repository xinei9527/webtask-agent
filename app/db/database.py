from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "webtask_agent.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_LOCK = threading.Lock()


def get_db_path() -> Path:
    return Path(os.getenv("WEBTASK_DB_PATH", str(DEFAULT_DB_PATH))).resolve()


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with _LOCK, get_connection() as conn:
        conn.executescript(schema)
        conn.commit()


def create_task_run(user_task: str) -> int:
    init_db()
    with _LOCK, get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO task_run (user_task, status) VALUES (?, ?)",
            (user_task, "running"),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_task_run(
    task_id: int,
    status: str,
    final_result: str | None = None,
    error_message: str | None = None,
    end: bool = False,
) -> None:
    end_time = datetime.utcnow().isoformat(timespec="seconds") if end else None
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            UPDATE task_run
            SET status = ?,
                final_result = COALESCE(?, final_result),
                error_message = ?,
                end_time = COALESCE(?, end_time)
            WHERE id = ?
            """,
            (status, final_result, error_message, end_time, task_id),
        )
        conn.commit()


def insert_trace(record: dict[str, Any]) -> int:
    with _LOCK, get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_trace (
                task_id, step_index, node_name, action_type, action_input,
                observation, screenshot_path, success, error_message, cost_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["task_id"],
                record["step_index"],
                record["node_name"],
                record.get("action_type"),
                record.get("action_input"),
                record.get("observation"),
                record.get("screenshot_path"),
                1 if record.get("success") else 0,
                record.get("error_message"),
                record.get("cost_ms"),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_task_run(task_id: int) -> dict[str, Any] | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM task_run WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_task_runs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_run ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_trace(task_id: int) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM agent_trace
            WHERE task_id = ?
            ORDER BY step_index ASC, id ASC
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]
