#!/usr/bin/env python3
"""Run a bounded release smoke through the installed google-routes Skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, TextIO


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
COMMUTE_MODULE_PATH = SCRIPT_DIR / "commute_analyzer.py"
SMOKE_MODES = ("TWO_WHEELER", "DRIVE")


def _load_commute_module():
    spec = importlib.util.spec_from_file_location(
        "commute_analyzer_for_release_smoke", COMMUTE_MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("無法載入 commute-analyzer CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


commute_analyzer = _load_commute_module()

DependencyRunner = Callable[
    [Path, str, object, dict[str, str]], tuple[int, str, str]
]
DependencySmokeRunner = Callable[
    [Path, Path, dict[str, str]], tuple[int, str, str]
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-billable-smoke",
        action="store_true",
        help="明確允許最多兩筆可能計費的 Compute Routes request",
    )
    parser.add_argument("input", type=Path, help="Skill 目錄外的私人 execution plan")
    return parser.parse_args(argv)


def run(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
    dependency_runner: DependencyRunner | None = None,
    dependency_smoke_runner: DependencySmokeRunner | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    environment = dict(os.environ if environ is None else environ)
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    if not arguments.confirm_billable_smoke:
        return _write_error(
            "SMOKE_CONFIRMATION_REQUIRED",
            "缺少 --confirm-billable-smoke；未執行任何 Routes API request",
            "$command",
            output,
            diagnostics,
        )

    input_path = arguments.input.resolve()
    if _is_within(input_path, _public_source_boundary()):
        return _write_error(
            "PRIVATE_PLAN_REQUIRED",
            "execution plan 必須保存在公開 repository 或 Skill 目錄外",
            "$input",
            output,
            diagnostics,
        )

    effective_now = datetime.now(timezone.utc) if now is None else now
    effective_cwd = Path.cwd() if cwd is None else cwd
    effective_home = Path.home() if home is None else home
    runner = (
        commute_analyzer._run_google_routes
        if dependency_runner is None
        else dependency_runner
    )
    smoke_runner = (
        _run_dependency_smoke
        if dependency_smoke_runner is None
        else dependency_smoke_runner
    )

    try:
        try:
            plan_value = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise commute_analyzer.InputError(
                "INVALID_SMOKE_PLAN",
                "私人 execution plan 無法讀取或不是有效 JSON",
                "$input",
            ) from error
        plan = commute_analyzer.validate_execution_plan(plan_value, now=effective_now)
        dependency = commute_analyzer._require_object(plan["dependency"], "$.dependency")
        dependency_path = commute_analyzer.discover_google_routes(
            environ=environment,
            commute_skill_dir=SKILL_DIR,
            cwd=effective_cwd,
            home=effective_home,
        )
        planned_dependency_path = Path(
            commute_analyzer._nonempty_string(
                dependency.get("path"), "$.dependency.path"
            )
        ).resolve()
        if dependency_path != planned_dependency_path:
            raise commute_analyzer.InputError(
                "PLAN_DEPENDENCY_CHANGED",
                "目前解析的 google-routes 路徑與 plan 不同；請重新執行 plan",
                "$.dependency.path",
            )

        cap_exit, cap_stdout, _ = commute_analyzer._call_dependency(
            runner, dependency_path, "capabilities", None, environment
        )
        if cap_exit != 0:
            raise commute_analyzer.InputError(
                "GOOGLE_ROUTES_INCOMPATIBLE",
                "google-routes capabilities 執行失敗；請重新執行 plan",
                "$.dependency",
            )
        try:
            capabilities_value = json.loads(cap_stdout)
        except json.JSONDecodeError as error:
            raise commute_analyzer.InputError(
                "GOOGLE_ROUTES_INCOMPATIBLE",
                "google-routes capabilities 未回傳有效 JSON",
                "$.dependency",
            ) from error
        current_dependency = commute_analyzer.validate_google_routes_capabilities(
            capabilities_value, dependency_path
        )
        if current_dependency != dependency:
            raise commute_analyzer.InputError(
                "PLAN_DEPENDENCY_CHANGED",
                "google-routes 能力或路徑已改變；請重新執行 plan",
                "$.dependency",
            )
        query = _build_smoke_query(plan)
        smoke_script = dependency_path / "scripts" / "smoke_test.py"
        if not smoke_script.is_file():
            raise commute_analyzer.InputError(
                "GOOGLE_ROUTES_SMOKE_UNAVAILABLE",
                "google-routes 缺少發布 smoke runner；請更新 google-routes",
                "$.dependency",
            )

        print(
            "即將執行發布 smoke：TWO_WHEELER 與 DRIVE 各一筆，"
            "最多 2 次 HTTP request，重試 0 次。",
            file=diagnostics,
        )
        smoke_stdout, smoke_exit = _execute_private_query(
            query,
            dependency_path=dependency_path,
            environment=environment,
            smoke_runner=smoke_runner,
        )
        evidence = _validate_smoke_evidence(
            smoke_stdout,
            smoke_exit,
            expected_dependency_version=str(current_dependency["skill_version"]),
        )
    except commute_analyzer.InputError as error:
        return _write_error(
            error.code, error.message, error.path, output, diagnostics
        )

    json.dump(
        {
            "schema_version": "2",
            "smoke_test": {
                "skill_name": "commute-analyzer",
                "skill_version": commute_analyzer.SKILL_VERSION,
                "google_routes_skill_version": current_dependency["skill_version"],
                "status": evidence["status"],
                "request_count": 2,
                "maximum_http_requests": 2,
                "max_retries": 0,
                "results": [
                    {
                        "travel_mode": item["travel_mode"],
                        "status": item["status"],
                        "attempts": item["attempts"],
                    }
                    for item in evidence["results"]
                ],
            },
        },
        output,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    output.write("\n")
    return smoke_exit


def _build_smoke_query(plan: Mapping[str, object]) -> dict[str, object]:
    samples = plan.get("samples")
    assert isinstance(samples, list)
    selected: dict[str, Mapping[str, object]] = {}
    for sample in samples:
        if isinstance(sample, dict):
            mode = sample.get("travel_mode")
            if mode in SMOKE_MODES and mode not in selected:
                selected[str(mode)] = sample
    if set(selected) != set(SMOKE_MODES):
        raise commute_analyzer.InputError(
            "SMOKE_MODES_REQUIRED",
            "發布 smoke 的 plan 必須同時包含 TWO_WHEELER 與 DRIVE",
            "$.schedule.travel_modes",
        )
    preview = commute_analyzer._require_object(plan.get("preview"), "$.preview")
    requests = []
    for mode in SMOKE_MODES:
        sample = selected[mode]
        requests.append(
            {
                "request_id": f"smoke-{mode.lower().replace('_', '-')}",
                "points": sample["points"],
                "travel_mode": mode,
                "departure_time": sample["departure_time"],
            }
        )
    return {
        "schema_version": "2",
        "profile": "itinerary_summary",
        "rate_limit_qpm": preview["rate_limit_qpm"],
        "requests": requests,
    }


def _execute_private_query(
    query: Mapping[str, object],
    *,
    dependency_path: Path,
    environment: dict[str, str],
    smoke_runner: DependencySmokeRunner,
) -> tuple[str, int]:
    query_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="commute-smoke-",
            delete=False,
        ) as stream:
            json.dump(query, stream, ensure_ascii=False, separators=(",", ":"))
            query_path = Path(stream.name)
        exit_code, stdout, _ = smoke_runner(
            dependency_path, query_path, environment
        )
        return stdout, exit_code
    except OSError as error:
        raise commute_analyzer.InputError(
            "PRIVATE_SMOKE_INPUT_FAILED",
            "無法建立暫時的私人 smoke query",
            "$smoke",
        ) from error
    finally:
        if query_path is not None:
            try:
                query_path.unlink(missing_ok=True)
            except OSError as error:
                raise commute_analyzer.InputError(
                    "PRIVATE_SMOKE_CLEANUP_FAILED",
                    "無法刪除暫時的私人 smoke query",
                    "$smoke",
                ) from error


def _validate_smoke_evidence(
    value: str,
    exit_code: int,
    *,
    expected_dependency_version: str,
) -> dict[str, object]:
    try:
        envelope = json.loads(value)
        smoke = envelope["smoke_test"]
        results = smoke["results"]
        if (
            envelope.get("schema_version") != "1"
            or smoke.get("skill_version") != expected_dependency_version
            or smoke.get("request_count") != 2
            or smoke.get("status")
            not in {"success", "degraded", "partial_success", "failure"}
            or exit_code not in {0, 3, 4}
            or not isinstance(results, list)
            or len(results) != 2
        ):
            raise ValueError
        expected_exit = {
            "success": 0,
            "degraded": 3,
            "partial_success": 3,
            "failure": 4,
        }[smoke["status"]]
        if exit_code != expected_exit:
            raise ValueError
        normalized = []
        for expected_mode, item in zip(SMOKE_MODES, results, strict=True):
            if (
                not isinstance(item, dict)
                or item.get("request_id")
                != f"smoke-{expected_mode.lower().replace('_', '-')}"
                or item.get("travel_mode") != expected_mode
                or item.get("status") not in {"success", "degraded", "error"}
                or item.get("attempts") != 1
            ):
                raise ValueError
            normalized.append(
                {
                    "travel_mode": expected_mode,
                    "status": item["status"],
                    "attempts": 1,
                }
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise commute_analyzer.InputError(
            "SMOKE_EVIDENCE_INVALID",
            "google-routes smoke 未回傳符合兩筆、零重試上限的證據",
            "$dependency.smoke_test",
        ) from error
    return {"status": smoke["status"], "results": normalized}


def _run_dependency_smoke(
    skill_path: Path,
    query_path: Path,
    environ: dict[str, str],
) -> tuple[int, str, str]:
    process = subprocess.run(
        [
            sys.executable,
            str(skill_path / "scripts" / "smoke_test.py"),
            "--confirm-billable-smoke",
            str(query_path),
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=skill_path,
        env=environ,
        check=False,
    )
    return process.returncode, process.stdout, process.stderr


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _public_source_boundary() -> Path:
    repository_candidate = SKILL_DIR.parent.parent
    if (repository_candidate / ".git").exists():
        return repository_candidate
    return SKILL_DIR


def _write_error(
    code: str,
    message: str,
    path: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    json.dump(
        {
            "schema_version": "2",
            "error": {"code": code, "path": path, "message": message},
        },
        stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    stdout.write("\n")
    print(f"發布 smoke 拒絕執行：{code}（{path}）。", file=stderr)
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
