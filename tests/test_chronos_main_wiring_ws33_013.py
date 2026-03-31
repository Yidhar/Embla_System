"""WS33-013: Verify Chronos scheduler wiring in EmblaRuntime."""

import json
from pathlib import Path
from unittest.mock import patch


def _make_runtime():
    """Create an EmblaRuntime instance without triggering real startup."""
    from main import EmblaRuntime, StartupOptions

    opts = StartupOptions(headless=True)
    # Use default runtime_config — constructor does not start services
    return EmblaRuntime(opts)


def test_embla_runtime_has_chronos_scheduler_attribute():
    """EmblaRuntime.__init__ must initialise _chronos_scheduler to None."""
    rt = _make_runtime()
    assert hasattr(rt, "_chronos_scheduler"), "_chronos_scheduler attribute missing from EmblaRuntime"
    assert rt._chronos_scheduler is None, "_chronos_scheduler should be None before initialize_services()"


def test_run_daily_checkpoint_creates_json(tmp_path, monkeypatch):
    """_run_daily_checkpoint should write a JSON file with expected keys."""
    rt = _make_runtime()

    # Pretend chronos is running so the checkpoint reflects that
    rt._chronos_scheduler = object()

    # Redirect scratch/runtime to tmp_path
    output_dir = tmp_path / "scratch" / "runtime"
    monkeypatch.chdir(tmp_path)

    rt._run_daily_checkpoint()

    # Find the generated file
    files = list((tmp_path / "scratch" / "runtime").glob("daily_checkpoint_*.json"))
    assert len(files) == 1, f"Expected 1 checkpoint file, found {len(files)}"

    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert "generated_at" in data
    assert data["type"] == "daily_checkpoint"
    assert "services" in data
    services = data["services"]
    for key in ("api_server", "supervisor", "chronos", "sdlc"):
        assert key in services, f"Missing service key: {key}"
    # chronos should be reported as running (we set it to a truthy object)
    assert services["chronos"] == "running"
