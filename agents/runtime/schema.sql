PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS workflow_state (
  workflow_id      TEXT PRIMARY KEY,
  task_id          TEXT NOT NULL,
  current_state    TEXT NOT NULL,
  retry_count      INTEGER NOT NULL DEFAULT 0,
  max_retries      INTEGER NOT NULL DEFAULT 0,
  last_error       TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_event (
  transition_id    TEXT PRIMARY KEY,
  workflow_id      TEXT NOT NULL,
  from_state       TEXT,
  to_state         TEXT NOT NULL,
  reason           TEXT,
  payload_json     TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_event_workflow_created
  ON workflow_event(workflow_id, created_at);

CREATE TABLE IF NOT EXISTS workflow_command (
  command_id        TEXT PRIMARY KEY,
  workflow_id       TEXT NOT NULL,
  step_name         TEXT NOT NULL,
  command_type      TEXT NOT NULL,
  idempotency_key   TEXT NOT NULL,
  fencing_epoch     INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL,
  attempt           INTEGER NOT NULL DEFAULT 1,
  max_attempt       INTEGER NOT NULL DEFAULT 1,
  last_error        TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE(workflow_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workflow_command_workflow_status
  ON workflow_command(workflow_id, status);

CREATE TABLE IF NOT EXISTS outbox_event (
  outbox_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_id       TEXT NOT NULL,
  event_type        TEXT NOT NULL,
  payload_json      TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending',
  dispatch_attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts      INTEGER NOT NULL DEFAULT 5,
  last_error        TEXT,
  next_retry_at     TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outbox_event_status_created
  ON outbox_event(status, created_at);

CREATE TABLE IF NOT EXISTS inbox_dedup (
  consumer          TEXT NOT NULL,
  message_id        TEXT NOT NULL,
  processed_at      TEXT NOT NULL,
  PRIMARY KEY(consumer, message_id)
);

