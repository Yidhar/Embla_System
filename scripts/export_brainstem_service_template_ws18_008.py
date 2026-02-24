"""Export WS18-008 brainstem supervisor deployment templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from system.brainstem_supervisor import BrainstemServiceSpec, BrainstemSupervisor


def main() -> int:
    parser = argparse.ArgumentParser(description="Export brainstem service supervision templates.")
    parser.add_argument("--service-name", default="naga-brainstem", help="Service name")
    parser.add_argument("--command", nargs="+", default=["python", "main.py", "--headless"], help="Service command")
    parser.add_argument("--working-dir", default=".", help="Working directory")
    parser.add_argument(
        "--restart-policy",
        default="on-failure",
        choices=["always", "on-failure", "never"],
        help="Restart policy",
    )
    parser.add_argument("--max-restarts", type=int, default=5, help="Max restart attempts before fallback")
    parser.add_argument("--restart-backoff", type=float, default=3.0, help="Restart backoff seconds")
    parser.add_argument(
        "--lightweight-fallback-command",
        nargs="*",
        default=["python", "main.py", "--lightweight"],
        help="Lightweight fallback command",
    )
    parser.add_argument("--state-file", default="logs/autonomous/brainstem_supervisor_state.json", help="Supervisor state file")
    parser.add_argument("--output-dir", default="scratch/brainstem_templates", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    supervisor = BrainstemSupervisor(state_file=Path(args.state_file), launcher=lambda _spec: 0)
    spec = BrainstemServiceSpec(
        service_name=args.service_name,
        command=args.command,
        working_dir=args.working_dir,
        restart_policy=args.restart_policy,
        max_restarts=args.max_restarts,
        restart_backoff_seconds=args.restart_backoff,
        lightweight_fallback_command=args.lightweight_fallback_command,
    )
    supervisor.register_service(spec)

    systemd_text = supervisor.render_systemd_unit(args.service_name)
    windows_plan = supervisor.render_windows_recovery_template(args.service_name)
    manifest = supervisor.build_supervisor_manifest()

    systemd_file = out_dir / f"{args.service_name}.service"
    windows_file = out_dir / f"{args.service_name}.windows-recovery.json"
    manifest_file = out_dir / f"{args.service_name}.manifest.json"
    systemd_file.write_text(systemd_text + "\n", encoding="utf-8")
    windows_file.write_text(json.dumps(windows_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"exported: {systemd_file}")
    print(f"exported: {windows_file}")
    print(f"exported: {manifest_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
