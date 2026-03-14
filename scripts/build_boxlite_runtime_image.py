#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from system.boxlite.manager import build_local_boxlite_runtime_image, load_boxlite_runtime_settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local Embla BoxLite runtime image")
    parser.add_argument("--runtime-profile", default="default", help="Runtime profile to build")
    parser.add_argument("--image-tag", default="", help="Override image tag")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_boxlite_runtime_settings()
    result = build_local_boxlite_runtime_image(
        settings,
        profile_name=str(args.runtime_profile or "default").strip() or "default",
        project_root=PROJECT_ROOT,
        image_tag=str(args.image_tag or "").strip() or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
