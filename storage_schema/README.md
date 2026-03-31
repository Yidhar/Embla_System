# Storage Schema

Canonical SQL schema files for runtime/event/workflow persistence live here.

- `brainstem_event_workflow.sql`: canonical schema for `event_log`, `workflow_command`, `outbox_event`, `inbox_dedup`.

Legacy compatibility:

- `memory/schema.sql` remains as a compatibility entrypoint and points to this canonical file.
