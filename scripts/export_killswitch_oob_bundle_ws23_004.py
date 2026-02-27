#!/usr/bin/env python3
"""WS23-004 export OOB-safe KillSwitch freeze/probe bundle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

from system.killswitch_guard import (
    build_oob_health_probe_plan,
    build_oob_killswitch_plan,
    validate_freeze_command,
    validate_oob_health_probe_plan,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_killswitch_oob_bundle(
    *,
    oob_allowlist: Sequence[str],
    probe_targets: Sequence[str],
    output_file: Path,
    dns_allow: bool = True,
    tcp_port: int = 22,
    ping_timeout_seconds: int = 2,
) -> Dict[str, Any]:
    allowlist = [str(item).strip() for item in oob_allowlist if str(item).strip()]
    targets = [str(item).strip() for item in probe_targets if str(item).strip()]
    if not allowlist:
        raise ValueError("oob_allowlist is required")
    if not targets:
        raise ValueError("probe_targets is required")

    freeze_plan = build_oob_killswitch_plan(
        oob_allowlist=allowlist,
        dns_allow=bool(dns_allow),
    )
    probe_plan = build_oob_health_probe_plan(
        oob_allowlist=allowlist,
        probe_targets=targets,
        tcp_port=int(tcp_port),
        ping_timeout_seconds=int(ping_timeout_seconds),
    )

    freeze_ok, freeze_reason = validate_freeze_command("\n".join(freeze_plan.commands))
    probe_ok, probe_reason = validate_oob_health_probe_plan(
        oob_allowlist=probe_plan.oob_allowlist,
        probe_targets=targets,
        commands=probe_plan.commands,
    )
    passed = bool(freeze_ok and probe_ok)

    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-004",
        "scenario": "export_killswitch_oob_bundle",
        "generated_at": _utc_iso(),
        "passed": passed,
        "dns_allow": bool(dns_allow),
        "tcp_port": int(tcp_port),
        "ping_timeout_seconds": int(ping_timeout_seconds),
        "oob_allowlist": list(freeze_plan.oob_allowlist),
        "probe_targets": targets,
        "freeze_plan": {
            "mode": freeze_plan.mode,
            "commands": list(freeze_plan.commands),
            "validation_ok": bool(freeze_ok),
            "validation_reason": freeze_reason,
        },
        "probe_plan": {
            "mode": probe_plan.mode,
            "commands": list(probe_plan.commands),
            "validation_ok": bool(probe_ok),
            "validation_reason": probe_reason,
        },
    }

    target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = str(target).replace("\\", "/")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export OOB-safe KillSwitch freeze/probe bundle")
    parser.add_argument("--oob-allowlist", nargs="+", required=True, help="Allowed egress recovery targets")
    parser.add_argument("--probe-targets", nargs="+", required=True, help="Probe targets covered by allowlist")
    parser.add_argument("--dns-allow", action="store_true", help="Allow DNS egress during freeze")
    parser.add_argument("--tcp-port", type=int, default=22, help="TCP health probe port")
    parser.add_argument("--ping-timeout-seconds", type=int, default=2, help="Ping/TCP probe timeout seconds")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/killswitch_oob_bundle_ws23_004.json"),
        help="Bundle output JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = export_killswitch_oob_bundle(
        oob_allowlist=list(args.oob_allowlist or []),
        probe_targets=list(args.probe_targets or []),
        output_file=args.output,
        dns_allow=bool(args.dns_allow),
        tcp_port=int(args.tcp_port),
        ping_timeout_seconds=int(args.ping_timeout_seconds),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "output": report.get("output_file"),
                "freeze_ok": (report.get("freeze_plan") or {}).get("validation_ok"),
                "probe_ok": (report.get("probe_plan") or {}).get("validation_ok"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
