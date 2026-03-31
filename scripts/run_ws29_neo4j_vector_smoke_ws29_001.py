#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from summer_memory.embedding_openai_compat import resolve_embedding_runtime_config
from summer_memory.quintuple_graph import (
    get_graph,
    get_vector_index_status,
    query_graph_by_keywords,
    store_quintuples,
)
from system.config import get_config


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool(value: Any) -> bool:
    return bool(value)


def run_smoke(*, strict: bool, output: Path) -> Dict[str, Any]:
    config = get_config()
    grag_cfg = config.grag
    embedding_cfg = resolve_embedding_runtime_config()

    checks: Dict[str, bool] = {
        "grag_enabled": _bool(grag_cfg.enabled),
        "neo4j_configured": _bool(
            str(grag_cfg.neo4j_uri or "").strip()
            and str(grag_cfg.neo4j_user or "").strip()
            and str(grag_cfg.neo4j_password or "").strip()
        ),
        "vector_index_enabled": _bool(getattr(grag_cfg, "vector_index_enabled", True)),
        "embedding_ready": embedding_cfg.ready,
    }
    reasons: List[str] = []

    graph = get_graph()
    checks["neo4j_connected"] = graph is not None

    vector_status = get_vector_index_status()
    checks["vector_status_known"] = str(vector_status.get("state", "")).strip().lower() not in {
        "",
        "probe_failed",
        "neo4j_unavailable",
    }

    smoke_tag = f"ws29_{uuid.uuid4().hex[:8]}"
    quintuples = [
        (
            f"WS29_ENTITY_{smoke_tag}_A",
            "SMOKE",
            "connects_to",
            f"WS29_ENTITY_{smoke_tag}_B",
            "SMOKE",
        )
    ]

    checks["smoke_write_ok"] = False
    checks["smoke_query_has_rows"] = False
    smoke_query_rows = 0
    if graph is not None:
        checks["smoke_write_ok"] = _bool(store_quintuples(quintuples))
        rows = query_graph_by_keywords([smoke_tag])
        smoke_query_rows = len(rows)
        checks["smoke_query_has_rows"] = smoke_query_rows > 0

    if strict:
        required_keys = [
            "grag_enabled",
            "neo4j_configured",
            "embedding_ready",
            "neo4j_connected",
            "smoke_write_ok",
            "smoke_query_has_rows",
        ]
        for key in required_keys:
            if not checks.get(key, False):
                reasons.append(f"{key}_failed")

        if checks.get("vector_index_enabled", False) and not checks.get("vector_status_known", False):
            reasons.append("vector_status_unknown")
        passed = len(reasons) == 0
    else:
        passed = checks.get("neo4j_connected", False)
        if not passed:
            reasons.append("neo4j_not_connected")

    report: Dict[str, Any] = {
        "task_id": "NGA-WS29-001",
        "scenario": "neo4j_vector_embedding_smoke",
        "generated_at": _utc_now_iso(),
        "passed": passed,
        "strict": strict,
        "checks": checks,
        "reasons": reasons,
        "vector_status": vector_status,
        "embedding_runtime": {
            "api_base_configured": bool(embedding_cfg.api_base),
            "api_key_configured": bool(embedding_cfg.api_key),
            "model": embedding_cfg.model,
            "dimensions": embedding_cfg.dimensions,
            "encoding_format": embedding_cfg.encoding_format,
            "max_input_tokens": embedding_cfg.max_input_tokens,
            "request_timeout_seconds": embedding_cfg.request_timeout_seconds,
        },
        "smoke_tag": smoke_tag,
        "smoke_query_rows": smoke_query_rows,
        "output_file": str(output),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WS29 Neo4j vector + embedding smoke")
    parser.add_argument("--strict", action="store_true", help="Enable strict pass/fail checks")
    parser.add_argument(
        "--output",
        default="scratch/reports/ws29_neo4j_vector_smoke_ws29_001.json",
        help="Report output path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).resolve()
    report = run_smoke(strict=bool(args.strict), output=output)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if bool(report.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
