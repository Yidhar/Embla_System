from __future__ import annotations

from core.mcp.isolated_worker import IsolatedWorkerRuntime


def test_isolated_worker_runtime_snapshot_critical_on_circuit_open(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.mcp.isolated_worker.get_plugin_worker_runtime_metrics",
        lambda: {
            "services": {
                "svc-a": {
                    "timeout_total": 0,
                    "circuit_open_total": 2,
                    "payload_reject_total": 0,
                    "output_budget_reject_total": 0,
                }
            }
        },
    )
    snapshot = IsolatedWorkerRuntime().snapshot()
    assert snapshot.status == "critical"
    assert snapshot.service_count == 1
    assert snapshot.circuit_open_total == 2


def test_isolated_worker_runtime_snapshot_warning_on_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.mcp.isolated_worker.get_plugin_worker_runtime_metrics",
        lambda: {
            "services": {
                "svc-a": {
                    "timeout_total": 1,
                    "circuit_open_total": 0,
                    "payload_reject_total": 0,
                    "output_budget_reject_total": 0,
                }
            }
        },
    )
    snapshot = IsolatedWorkerRuntime().snapshot()
    assert snapshot.status == "warning"
    assert snapshot.timeout_total == 1
