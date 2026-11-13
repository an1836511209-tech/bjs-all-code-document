CREATE TABLE IF NOT EXISTS report_agent_tasks (
  task_id VARCHAR(64) PRIMARY KEY,
  workspace_id VARCHAR(64) NOT NULL UNIQUE,
  status VARCHAR(32) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS report_agent_sessions (
  session_id VARCHAR(64) PRIMARY KEY,
  task_id VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_report_agent_session_task FOREIGN KEY (task_id) REFERENCES report_agent_tasks(task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS report_agent_runs (
  run_id VARCHAR(64) PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  task_id VARCHAR(64) NOT NULL,
  workspace_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  user_message LONGTEXT NOT NULL,
  assistant_text LONGTEXT NULL,
  trace_json JSON NULL,
  error_type VARCHAR(128) NULL,
  skill_name VARCHAR(64) NULL,
  skill_route VARCHAR(64) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_report_agent_runs_task_created (task_id, created_at),
  CONSTRAINT fk_report_agent_run_task FOREIGN KEY (task_id) REFERENCES report_agent_tasks(task_id),
  CONSTRAINT fk_report_agent_run_session FOREIGN KEY (session_id) REFERENCES report_agent_sessions(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS report_agent_artifacts (
  artifact_id VARCHAR(64) PRIMARY KEY,
  run_id VARCHAR(64) NOT NULL,
  task_id VARCHAR(64) NOT NULL,
  filename VARCHAR(255) NOT NULL,
  sha256 CHAR(64) NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL,
  bucket_name VARCHAR(255) NOT NULL,
  object_key VARCHAR(1024) NOT NULL,
  download_url TEXT NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_report_agent_artifact_object (object_key(255)),
  INDEX idx_report_agent_artifacts_task_created (task_id, created_at),
  CONSTRAINT fk_report_agent_artifact_run FOREIGN KEY (run_id) REFERENCES report_agent_runs(run_id),
  CONSTRAINT fk_report_agent_artifact_task FOREIGN KEY (task_id) REFERENCES report_agent_tasks(task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
