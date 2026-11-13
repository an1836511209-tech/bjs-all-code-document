-- Existing databases were created before skill routing was persisted.
-- report-agent-db-migrate treats MySQL 1060 (duplicate column) as already applied.
ALTER TABLE report_agent_runs
  ADD COLUMN skill_name VARCHAR(64) NULL AFTER error_type;

ALTER TABLE report_agent_runs
  ADD COLUMN skill_route VARCHAR(64) NULL AFTER skill_name;
