-- Core event and workflow schema for autonomous SDLC.

CREATE TABLE IF NOT EXISTS event_log (
  tenant_id         TEXT NOT NULL,
  project_id        TEXT NOT NULL,
  event_seq         BIGINT NOT NULL,
  event_id          TEXT NOT NULL,
  workflow_id       TEXT NOT NULL,
  event_type        TEXT NOT NULL,
  payload_json      TEXT NOT NULL,
  event_time        TEXT NOT NULL,
  system_time       TEXT NOT NULL,
  producer          TEXT NOT NULL,
  idempotency_key   TEXT NOT NULL,
  fencing_epoch     BIGINT NOT NULL,
  PRIMARY KEY (tenant_id, project_id, event_seq),
  UNIQUE (tenant_id, project_id, event_id),
  UNIQUE (tenant_id, project_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS workflow_command (
  command_id        TEXT PRIMARY KEY,
  workflow_id       TEXT NOT NULL,
  step_name         TEXT NOT NULL,
  command_type      TEXT NOT NULL,
  idempotency_key   TEXT NOT NULL,
  fencing_epoch     BIGINT NOT NULL,
  status            TEXT NOT NULL,
  attempt           INTEGER NOT NULL,
  max_attempt       INTEGER NOT NULL,
  last_error        TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_event (
  outbox_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_id       TEXT NOT NULL,
  event_type        TEXT NOT NULL,
  payload_json      TEXT NOT NULL,
  status            TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inbox_dedup (
  consumer          TEXT NOT NULL,
  message_id        TEXT NOT NULL,
  processed_at      TEXT NOT NULL,
  PRIMARY KEY (consumer, message_id)
);
