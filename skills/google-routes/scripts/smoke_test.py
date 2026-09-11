#!/usr/bin/env python3
"""Run a deliberately bounded and redacted real Google Routes smoke test."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import google_routes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-billable-smoke",
        action="store_true",
        help="Explicitly allow at most two billable Compute Routes requests",
    )
    parser.add_argument("input", type=Path, help="Private query envelope outside the repository")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    if not arguments.confirm_billable_smoke:
        print("拒絕執行：缺少 --confirm-billable-smoke。", file=sys.stderr)
        return 2
    try:
        payload = json.loads(arguments.input.read_text(encoding="utf-8"))
        validated = google_routes.validate_batch(payload)
    except (OSError, json.JSONDecodeError, google_routes.InputError) as error:
        print(f"smoke input 無效：{type(error).__name__}", file=sys.stderr)
        return 2
    requests = validated["requests"]
    modes = [item["travel_mode"] for item in requests]
    if len(requests) > 2 or any(modes.count(mode) > 1 for mode in set(modes)):
        print("拒絕執行：最多兩筆，且每個 travel mode 最多一筆。", file=sys.stderr)
        return 2
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        print("拒絕執行：尚未設定 GOOGLE_MAPS_API_KEY。", file=sys.stderr)
        return 2
    result, exit_code = google_routes.execute_batch(validated, api_key=api_key)
    evidence = {
        "schema_version": google_routes.SCHEMA_VERSION,
        "smoke_test": {
            "skill_version": google_routes.SKILL_VERSION,
            "status": result["status"],
            "request_count": len(requests),
            "results": [
                {
                    "request_id": item["request_id"],
                    "travel_mode": item["travel_mode"],
                    "status": item["status"],
                    "attempts": item["attempts"],
                }
                for item in result["results"]
            ],
        },
    }
    json.dump(evidence, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return exit_code


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
