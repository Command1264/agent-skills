from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMUTE_MODULE_PATH = (
    ROOT / "skills" / "commute-analyzer" / "scripts" / "commute_analyzer.py"
)
SMOKE_MODULE_PATH = ROOT / "skills" / "commute-analyzer" / "scripts" / "smoke_test.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


commute_analyzer = load_module("commute_analyzer_for_smoke", COMMUTE_MODULE_PATH)
commute_smoke = load_module("commute_smoke", SMOKE_MODULE_PATH)


NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
PRIVATE_ADDRESS = "測試私人地址 123 號"
PRIVATE_COMPANY = "測試私人公司"


def google_routes_path() -> Path:
    return (ROOT / "skills" / "google-routes").resolve()


def dependency() -> dict[str, object]:
    return {
        "path": str(google_routes_path()),
        "skill_version": "2.1.0",
        "cli_contract_version": "2.0.0",
        "schema_version": "2",
        "travel_modes": ["DRIVE", "TWO_WHEELER"],
        "output_profile": "itinerary_summary",
        "itinerary_limits": {
            "minimum_points": 2,
            "maximum_points": 12,
            "maximum_intermediate_waypoints": 10,
            "waypoint_order": "fixed",
        },
    }


def plan(*, travel_modes: list[str] | None = None) -> dict[str, object]:
    return commute_analyzer.build_plan(
        {
            "schema_version": "1",
            "start_date": "2026-09-14",
            "weeks": 1,
            "weekdays": [1],
            "travel_modes": travel_modes or ["TWO_WHEELER", "DRIVE"],
        },
        {
            "schema_version": "1",
            "home": {
                "label": "private-home",
                "location": {"address": PRIVATE_ADDRESS},
            },
            "companies": [
                {
                    "id": "private-company-id",
                    "name": PRIVATE_COMPANY,
                    "location": {"place_id": "ChIJPrivateCompany"},
                }
            ],
            "utc_offset": "+08:00",
            "morning_departure_time": "08:00",
            "evening_departure_time": "18:00",
        },
        dependency(),
        now=NOW,
    )


def capabilities_runner(
    skill_path: Path,
    command: str,
    payload: object,
    environ: dict[str, str],
) -> tuple[int, str, str]:
    assert skill_path == google_routes_path()
    assert command == "capabilities"
    assert payload is None
    return (
        0,
        json.dumps(
            {
                "skill_name": "google-routes",
                "skill_version": "2.1.0",
                "cli_contract_version": "2.0.0",
                "schema_versions": ["1", "2"],
                "travel_modes": ["DRIVE", "TWO_WHEELER"],
                "output_profiles": ["summary", "itinerary_summary"],
                "itinerary_limits": {
                    "minimum_points": 2,
                    "maximum_points": 12,
                    "maximum_intermediate_waypoints": 10,
                    "waypoint_order": "fixed",
                    "intermediate_type": "stopover",
                    "optimization_supported": False,
                },
            }
        ),
        "",
    )


class CommuteSmokeTests(unittest.TestCase):
    def _write_plan(self, root: Path, value: dict[str, object] | None = None) -> Path:
        path = root / "private-plan.json"
        path.write_text(json.dumps(value or plan()), encoding="utf-8")
        return path

    def test_missing_confirmation_stops_before_reading_or_dependency(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        calls: list[str] = []

        exit_code = commute_smoke.run(
            ["missing-plan.json"],
            stdout=stdout,
            stderr=stderr,
            environ={},
            now=NOW,
            dependency_runner=lambda *args: calls.append("capabilities"),
            dependency_smoke_runner=lambda *args: calls.append("smoke"),
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, [])
        self.assertEqual(
            json.loads(stdout.getvalue())["error"]["code"],
            "SMOKE_CONFIRMATION_REQUIRED",
        )
        self.assertNotIn("missing-plan.json", stderr.getvalue())

    def test_one_request_per_mode_has_no_retry_and_redacts_evidence(self) -> None:
        observed: dict[str, object] = {}

        def fake_smoke_runner(
            skill_path: Path,
            query_path: Path,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            observed["skill_path"] = skill_path
            observed["query"] = json.loads(query_path.read_text(encoding="utf-8"))
            observed["query_path"] = query_path
            observed["legacy_api_key_present"] = "GOOGLE_MAPS_API_KEY" in environ
            return (
                0,
                json.dumps(
                    {
                        "schema_version": "1",
                        "smoke_test": {
                            "skill_version": "2.1.0",
                            "status": "success",
                            "request_count": 2,
                            "results": [
                                {
                                    "request_id": "smoke-two-wheeler",
                                    "travel_mode": "TWO_WHEELER",
                                    "status": "success",
                                    "attempts": 1,
                                },
                                {
                                    "request_id": "smoke-drive",
                                    "travel_mode": "DRIVE",
                                    "status": "success",
                                    "attempts": 1,
                                },
                            ],
                        },
                    }
                ),
                "",
            )

        with tempfile.TemporaryDirectory() as directory:
            input_path = self._write_plan(Path(directory))
            stdout = io.StringIO()
            stderr = io.StringIO()
            exit_code = commute_smoke.run(
                ["--confirm-billable-smoke", str(input_path)],
                stdout=stdout,
                stderr=stderr,
                environ={},
                now=NOW,
                cwd=ROOT,
                home=Path(directory),
                dependency_runner=capabilities_runner,
                dependency_smoke_runner=fake_smoke_runner,
            )

        self.assertEqual(exit_code, 0)
        query = observed["query"]
        self.assertEqual(query["profile"], "itinerary_summary")
        self.assertEqual(len(query["requests"]), 2)
        self.assertEqual(
            [(item["request_id"], item["travel_mode"]) for item in query["requests"]],
            [("smoke-two-wheeler", "TWO_WHEELER"), ("smoke-drive", "DRIVE")],
        )
        self.assertFalse(observed["legacy_api_key_present"])
        self.assertFalse(observed["query_path"].exists())

        evidence = json.loads(stdout.getvalue())
        self.assertEqual(
            evidence,
            {
                "schema_version": "2",
                "smoke_test": {
                    "skill_name": "commute-analyzer",
                    "skill_version": "2.0.0",
                    "google_routes_skill_version": "2.1.0",
                    "status": "success",
                    "request_count": 2,
                    "maximum_http_requests": 2,
                    "max_retries": 0,
                    "results": [
                        {"travel_mode": "TWO_WHEELER", "status": "success", "attempts": 1},
                        {"travel_mode": "DRIVE", "status": "success", "attempts": 1},
                    ],
                },
            },
        )
        combined = stdout.getvalue() + stderr.getvalue()
        for secret in (PRIVATE_ADDRESS, PRIVATE_COMPANY, "ChIJPrivateCompany"):
            self.assertNotIn(secret, combined)

    def test_plan_must_include_both_smoke_modes(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            input_path = self._write_plan(Path(directory), plan(travel_modes=["DRIVE"]))
            stdout = io.StringIO()
            exit_code = commute_smoke.run(
                ["--confirm-billable-smoke", str(input_path)],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={},
                now=NOW,
                cwd=ROOT,
                home=Path(directory),
                dependency_runner=capabilities_runner,
                dependency_smoke_runner=lambda *args: calls.append("smoke"),
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "SMOKE_MODES_REQUIRED")

    def test_dependency_evidence_with_retry_is_rejected(self) -> None:
        def retrying_smoke(*args) -> tuple[int, str, str]:
            return (
                0,
                json.dumps(
                    {
                        "schema_version": "1",
                        "smoke_test": {
                            "skill_version": "2.1.0",
                            "status": "success",
                            "request_count": 2,
                            "results": [
                                {
                                    "request_id": "smoke-two-wheeler",
                                    "travel_mode": "TWO_WHEELER",
                                    "status": "success",
                                    "attempts": 2,
                                },
                                {
                                    "request_id": "smoke-drive",
                                    "travel_mode": "DRIVE",
                                    "status": "success",
                                    "attempts": 1,
                                },
                            ],
                        },
                    }
                ),
                "",
            )

        with tempfile.TemporaryDirectory() as directory:
            input_path = self._write_plan(Path(directory))
            stdout = io.StringIO()
            exit_code = commute_smoke.run(
                ["--confirm-billable-smoke", str(input_path)],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={},
                now=NOW,
                cwd=ROOT,
                home=Path(directory),
                dependency_runner=capabilities_runner,
                dependency_smoke_runner=retrying_smoke,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "SMOKE_EVIDENCE_INVALID")

    def test_degraded_provider_result_preserves_release_smoke_exit_code(self) -> None:
        def degraded_smoke(*args) -> tuple[int, str, str]:
            return (
                3,
                json.dumps(
                    {
                        "schema_version": "1",
                        "smoke_test": {
                            "skill_version": "2.1.0",
                            "status": "degraded",
                            "request_count": 2,
                            "results": [
                                {
                                    "request_id": "smoke-two-wheeler",
                                    "travel_mode": "TWO_WHEELER",
                                    "status": "degraded",
                                    "attempts": 1,
                                },
                                {
                                    "request_id": "smoke-drive",
                                    "travel_mode": "DRIVE",
                                    "status": "success",
                                    "attempts": 1,
                                },
                            ],
                        },
                    }
                ),
                "",
            )

        with tempfile.TemporaryDirectory() as directory:
            input_path = self._write_plan(Path(directory))
            stdout = io.StringIO()
            exit_code = commute_smoke.run(
                ["--confirm-billable-smoke", str(input_path)],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={},
                now=NOW,
                cwd=ROOT,
                home=Path(directory),
                dependency_runner=capabilities_runner,
                dependency_smoke_runner=degraded_smoke,
            )

        self.assertEqual(exit_code, 3)
        self.assertEqual(json.loads(stdout.getvalue())["smoke_test"]["status"], "degraded")

    def test_dependency_credential_error_is_sanitized(self) -> None:
        calls: list[str] = []

        def missing_credentials(*args) -> tuple[int, str, str]:
            calls.append("smoke")
            return (
                2,
                json.dumps(
                    {
                        "schema_version": "1",
                        "error": {
                            "code": "credential_file_not_found",
                            "path": "$credential_file",
                            "message": "private credential detail",
                        },
                    }
                ),
                "private stderr detail",
            )

        with tempfile.TemporaryDirectory() as directory:
            input_path = self._write_plan(Path(directory))
            stdout = io.StringIO()
            exit_code = commute_smoke.run(
                ["--confirm-billable-smoke", str(input_path)],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={},
                now=NOW,
                cwd=ROOT,
                home=Path(directory),
                dependency_runner=capabilities_runner,
                dependency_smoke_runner=missing_credentials,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, ["smoke"])
        error = json.loads(stdout.getvalue())["error"]
        self.assertEqual(error["code"], "SMOKE_EVIDENCE_INVALID")
        self.assertNotIn("private credential detail", json.dumps(error))
        self.assertNotIn("private stderr detail", json.dumps(error))

    def test_plan_inside_public_repository_is_rejected(self) -> None:
        stdout = io.StringIO()
        exit_code = commute_smoke.run(
            [
                "--confirm-billable-smoke",
                str(ROOT / "skills" / "commute-analyzer" / "examples" / "plan.json"),
            ],
            stdout=stdout,
            stderr=io.StringIO(),
            environ={},
            now=NOW,
            dependency_runner=capabilities_runner,
            dependency_smoke_runner=lambda *args: self.fail("不得執行 smoke"),
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "PRIVATE_PLAN_REQUIRED")


if __name__ == "__main__":
    unittest.main()
