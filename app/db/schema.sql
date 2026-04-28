CREATE TABLE IF NOT EXISTS task_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_task TEXT NOT NULL,
    status TEXT NOT NULL,
    final_result TEXT,
    error_message TEXT,
    start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME
);

CREATE TABLE IF NOT EXISTS agent_trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    step_index INTEGER NOT NULL,
    node_name TEXT NOT NULL,
    action_type TEXT,
    action_input TEXT,
    observation TEXT,
    screenshot_path TEXT,
    success INTEGER,
    error_message TEXT,
    cost_ms INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_trace_task_id
ON agent_trace(task_id, step_index, id);
