from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "skills" / "commute-analyzer" / "scripts" / "commute_analyzer.py"
)
SPEC = importlib.util.spec_from_file_location("commute_analyzer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
commute_analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(commute_analyzer)


def private_config() -> dict[str, object]:
    return {
        "schema_version": "1",
        "home": {
            "label": "home",
            "location": {"address": "示例市住家路 1 號"},
        },
        "companies": [
            {
                "id": "acme",
                "name": "範例公司",
                "location": {"place_id": "ChIJExampleCompany"},
            }
        ],
        "utc_offset": "+08:00",
        "morning_departure_time": "08:00",
        "evening_departure_time": "18:00",
    }


def dependency() -> dict[str, object]:
    return {
        "path": "C:/skills/google-routes",
        "skill_version": "1.0.0",
        "cli_contract_version": "1.0.0",
        "schema_version": "1",
        "travel_modes": ["DRIVE", "TWO_WHEELER"],
        "output_profile": "summary",
    }


def route_result_for_plan(
    plan: dict[str, object], overrides: dict[str, dict[str, object]] | None = None
) -> dict[str, object]:
    replacements = overrides or {}
    results: list[dict[str, object]] = []
    for sample in plan["samples"]:
        result: dict[str, object] = {
            "request_id": sample["request_id"],
            "status": "success",
            "travel_mode": sample["travel_mode"],
            "distance_meters": 10000,
            "duration_seconds": 600,
            "static_duration_seconds": 540,
            "warnings": [],
            "fallback": None,
            "origin_place_id": None,
            "destination_place_id": None,
            "attempts": 1,
        }
        result.update(replacements.get(sample["request_id"], {}))
        if result["status"] == "error":
            result = {
                "request_id": sample["request_id"],
                "status": "error",
                "travel_mode": sample["travel_mode"],
                "error": {"code": "NETWORK_ERROR", "message": "暫時失敗", "retryable": True},
                "attempts": 3,
            }
        results.append(result)
    return {
        "schema_version": "1",
        "cli_contract_version": "1.0.0",
        "profile": "summary",
        "status": "success",
        "results": results,
    }


class CapabilitiesTests(unittest.TestCase):
    def test_capabilities_is_offline_and_describes_v1_contract(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = commute_analyzer.run_cli(
            ["capabilities"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=stderr,
            environ={},
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "skill_name": "commute-analyzer",
                "skill_version": "1.0.0",
                "cli_contract_version": "1.0.0",
                "schema_versions": ["1"],
                "commands": ["capabilities", "plan", "run"],
                "required_google_routes": {
                    "skill_major": 1,
                    "cli_contract_version": "1.0.0",
                    "schema_version": "1",
                    "travel_modes": ["DRIVE", "TWO_WHEELER"],
                    "output_profile": "summary",
                },
                "default_weeks": 1,
                "default_weekdays": [1, 2, 3, 4, 5],
                "default_travel_modes": ["TWO_WHEELER", "DRIVE"],
                "default_confirmation_threshold": 20,
            },
        )


class DependencyTests(unittest.TestCase):
    @staticmethod
    def _make_skill(path: Path) -> None:
        (path / "scripts").mkdir(parents=True)
        (path / "SKILL.md").write_text("---\nname: google-routes\n---\n", encoding="utf-8")
        (path / "scripts" / "google_routes.py").write_text("", encoding="utf-8")

    def test_missing_google_routes_fails_closed_with_install_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            with self.assertRaises(commute_analyzer.InputError) as context:
                commute_analyzer.discover_google_routes(
                    environ={},
                    commute_skill_dir=root / "commute-analyzer",
                    cwd=root / "project",
                    home=root / "home",
                )

        self.assertEqual(context.exception.code, "GOOGLE_ROUTES_NOT_FOUND")
        self.assertIn(
            "npx skills add Command1264/agent-skills --skill google-routes",
            context.exception.message,
        )

    def test_dependency_resolution_uses_the_documented_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commute_dir = root / "installed" / "commute-analyzer"
            override = root / "override" / "google-routes"
            sibling = commute_dir.parent / "google-routes"
            project = root / "project" / ".agents" / "skills" / "google-routes"
            user = root / "home" / ".agents" / "skills" / "google-routes"
            for candidate in (override, sibling, project, user):
                self._make_skill(candidate)

            selected = commute_analyzer.discover_google_routes(
                environ={"GOOGLE_ROUTES_SKILL_DIR": str(override)},
                commute_skill_dir=commute_dir,
                cwd=root / "project",
                home=root / "home",
            )

        self.assertEqual(selected, override.resolve())

    def test_incompatible_google_routes_capabilities_fail_closed(self) -> None:
        capabilities = {
            "skill_name": "google-routes",
            "skill_version": "2.0.0",
            "cli_contract_version": "2.0.0",
            "schema_versions": ["2"],
            "travel_modes": ["DRIVE"],
            "output_profiles": ["raw"],
        }

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_google_routes_capabilities(
                capabilities, Path("C:/skills/google-routes")
            )

        self.assertEqual(context.exception.code, "GOOGLE_ROUTES_INCOMPATIBLE")
        self.assertIn("更新 google-routes", context.exception.message)

    def test_dependency_process_error_becomes_structured_cli_error(self) -> None:
        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path, command, payload, environ
            raise OSError("private operating system detail")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            self._make_skill(google_routes)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(private_config()), encoding="utf-8")
            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                ["plan", "--config", str(config_path)],
                stdin=io.StringIO('{"schema_version":"1"}'),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"GOOGLE_ROUTES_SKILL_DIR": str(google_routes)},
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 2)
        error = json.loads(stdout.getvalue())["error"]
        self.assertEqual(error["code"], "GOOGLE_ROUTES_PROCESS_FAILED")
        self.assertNotIn("private operating system detail", json.dumps(error))


class PlanTests(unittest.TestCase):
    def test_public_examples_reproduce_the_checked_in_plan(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        config = json.loads((examples / "config.json").read_text(encoding="utf-8"))
        request = json.loads(
            (examples / "plan-request.json").read_text(encoding="utf-8")
        )
        expected = json.loads((examples / "plan.json").read_text(encoding="utf-8"))

        actual = commute_analyzer.build_plan(
            request,
            config,
            {
                "path": "/opt/skills/google-routes",
                "skill_version": "1.0.0",
                "cli_contract_version": "1.0.0",
                "schema_version": "1",
                "travel_modes": ["DRIVE", "TWO_WHEELER"],
                "output_profile": "summary",
            },
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(actual, expected)
        self.assertEqual(
            commute_analyzer.validate_execution_plan(
                expected,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            ),
            expected,
        )

    def test_default_plan_expands_next_workweek_without_external_calls(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["schedule"]["dates"], [
            "2026-09-14",
            "2026-09-15",
            "2026-09-16",
            "2026-09-17",
            "2026-09-18",
        ])
        self.assertEqual(len(plan["samples"]), 20)
        self.assertEqual(plan["preview"]["request_count"], 20)
        self.assertEqual(plan["preview"]["confirmation_required"], False)
        self.assertEqual(
            plan["preview"]["estimated_sku_requests"],
            {"routes_compute_pro": 10, "routes_compute_enterprise": 10},
        )
        self.assertEqual(plan["samples"][0]["direction"], "outbound")
        self.assertEqual(plan["samples"][0]["travel_mode"], "TWO_WHEELER")
        self.assertEqual(
            plan["samples"][0]["departure_time"], "2026-09-14T08:00:00+08:00"
        )
        self.assertRegex(plan["plan_id"], r"^sha256:[0-9a-f]{64}$")

    def test_plan_cli_checks_capabilities_but_never_runs_route_queries(self) -> None:
        calls: list[str] = []

        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path, payload, environ
            calls.append(command)
            if command != "capabilities":
                self.fail("plan 不得呼叫 google-routes query")
            return 0, json.dumps({
                "skill_name": "google-routes",
                "skill_version": "1.0.0",
                "cli_contract_version": "1.0.0",
                "schema_versions": ["1"],
                "travel_modes": ["DRIVE", "TWO_WHEELER"],
                "output_profiles": ["summary"],
            }), ""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(private_config()), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["plan", "--config", str(config_path)],
                stdin=io.StringIO('{"schema_version":"1"}'),
                stdout=stdout,
                stderr=stderr,
                environ={"GOOGLE_ROUTES_SKILL_DIR": str(google_routes)},
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["capabilities"])
        self.assertEqual(json.loads(stdout.getvalue())["preview"]["request_count"], 20)
        self.assertIn("不會呼叫 Routes API", stderr.getvalue())

    def test_modified_plan_is_rejected_before_execution(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["samples"][0]["departure_time"] = "2026-09-14T09:00:00+08:00"

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "PLAN_ID_MISMATCH")

    def test_rehashed_plan_with_inconsistent_preview_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["preview"]["maximum_http_requests"] = 999
        content = {key: value for key, value in plan.items() if key != "plan_id"}
        plan["plan_id"] = commute_analyzer._content_id(content)

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_PLAN")
        self.assertEqual(context.exception.path, "$.preview.maximum_http_requests")

    def test_rehashed_plan_with_inconsistent_schedule_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["schedule"]["travel_modes"] = ["DRIVE"]
        content = {key: value for key, value in plan.items() if key != "plan_id"}
        plan["plan_id"] = commute_analyzer._content_id(content)

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_PLAN")
        self.assertEqual(context.exception.path, "$.schedule.travel_modes")

    def test_expired_plan_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "PLAN_EXPIRED")

    def test_plan_parameters_control_weeks_weekdays_times_and_company(self) -> None:
        plan = commute_analyzer.build_plan(
            {
                "schema_version": "1",
                "start_date": "2026-09-13",
                "weeks": 2,
                "weekdays": [2, 4],
                "morning_departure_time": "07:30",
                "evening_departure_time": "17:45",
                "additional_companies": [
                    {
                        "id": "beta",
                        "name": "第二家公司",
                        "location": {"address": "示例市公司路 2 號"},
                    }
                ],
            },
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["schedule"]["dates"], [
            "2026-09-15",
            "2026-09-17",
            "2026-09-22",
            "2026-09-24",
        ])
        self.assertEqual(plan["preview"]["company_count"], 2)
        self.assertEqual(plan["preview"]["request_count"], 32)
        self.assertEqual(plan["samples"][0]["departure_time"], "2026-09-15T07:30:00+08:00")
        self.assertEqual(plan["samples"][2]["departure_time"], "2026-09-15T17:45:00+08:00")
        self.assertEqual(
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            ),
            plan,
        )


class RunTests(unittest.TestCase):
    @staticmethod
    def _compatible_capabilities() -> dict[str, object]:
        return {
            "skill_name": "google-routes",
            "skill_version": "1.0.0",
            "cli_contract_version": "1.0.0",
            "schema_versions": ["1"],
            "travel_modes": ["DRIVE", "TWO_WHEELER"],
            "output_profiles": ["summary"],
        }

    def test_complete_run_calculates_statistics_and_writes_private_outputs(self) -> None:
        calls: list[str] = []

        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path
            calls.append(command)
            if command == "capabilities":
                return 0, json.dumps({
                    "skill_name": "google-routes",
                    "skill_version": "1.0.0",
                    "cli_contract_version": "1.0.0",
                    "schema_versions": ["1"],
                    "travel_modes": ["DRIVE", "TWO_WHEELER"],
                    "output_profiles": ["summary"],
                }), ""
            self.assertEqual(environ["GOOGLE_MAPS_API_KEY"], "test-only-key")
            requests = payload["requests"]
            results = []
            for request in requests:
                duration = {
                    ("outbound", "TWO_WHEELER"): 600,
                    ("outbound", "DRIVE"): 900,
                    ("return", "TWO_WHEELER"): 720,
                    ("return", "DRIVE"): 840,
                }[(request["request_id"].split(".")[2], request["travel_mode"])]
                results.append({
                    "request_id": request["request_id"],
                    "status": "success",
                    "travel_mode": request["travel_mode"],
                    "distance_meters": 10000,
                    "duration_seconds": duration,
                    "static_duration_seconds": duration - 60,
                    "warnings": [],
                    "fallback": None,
                    "origin_place_id": None,
                    "destination_place_id": None,
                    "attempts": 1,
                })
            return 0, json.dumps({
                "schema_version": "1",
                "cli_contract_version": "1.0.0",
                "profile": "summary",
                "status": "success",
                "results": results,
            }), ""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            dependency_info = dependency()
            dependency_info["path"] = str(google_routes.resolve())
            plan = commute_analyzer.build_plan(
                {"schema_version": "1"},
                private_config(),
                dependency_info,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            output_dir = root / "reports"

            exit_code = commute_analyzer.run_cli(
                ["run", "--output-dir", str(output_dir)],
                stdin=io.StringIO(json.dumps(plan)),
                stdout=stdout,
                stderr=stderr,
                environ={
                    "GOOGLE_MAPS_API_KEY": "test-only-key",
                    "GOOGLE_ROUTES_SKILL_DIR": str(google_routes),
                    "XDG_DATA_HOME": str(root / "data"),
                },
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )
            result = json.loads(stdout.getvalue())
            report_json = Path(result["outputs"]["json_report"])
            report_markdown = Path(result["outputs"]["markdown_report"])
            ledger = root / "data" / "command1264-skills" / "commute-analyzer" / "usage.jsonl"

            self.assertTrue(report_json.is_file())
            self.assertTrue(report_markdown.is_file())
            report_json_text = report_json.read_text(encoding="utf-8")
            ledger_text = ledger.read_text(encoding="utf-8")
            report_text = report_markdown.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["capabilities", "query"])
        self.assertEqual(result["status"], "success")
        motorcycle = result["companies"][0]["modes"]["TWO_WHEELER"]
        self.assertEqual(motorcycle["statistics"]["daily_round_trip"]["average_seconds"], 1320)
        self.assertEqual(motorcycle["weekly_total_seconds"], 6600)
        self.assertEqual(motorcycle["four_week_month_estimate_seconds"], 26400)
        self.assertEqual(result["ranking"][0]["company_id"], "acme")
        self.assertIn("去程：平均", report_text)
        self.assertIn("回程：平均", report_text)
        self.assertIn("每日來回：平均", report_text)
        self.assertIn("四週月估算", report_text)
        self.assertNotIn("示例市住家路", report_text)
        self.assertNotIn("示例市住家路", report_json_text)
        self.assertNotIn("ChIJExampleCompany", report_json_text)
        self.assertNotIn("test-only-key", ledger_text)
        self.assertNotIn("duration", ledger_text)

    def test_over_threshold_requires_confirmation_of_the_same_plan(self) -> None:
        config = private_config()
        config["companies"].append({
            "id": "beta",
            "name": "第二家公司",
            "location": {"address": "示例市公司路 2 號"},
        })
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            config,
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        stdout = io.StringIO()

        exit_code = commute_analyzer.run_cli(
            ["run"],
            stdin=io.StringIO(json.dumps(plan)),
            stdout=stdout,
            stderr=io.StringIO(),
            environ={"GOOGLE_MAPS_API_KEY": "test-only-key"},
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["preview"]["request_count"], 40)
        self.assertEqual(exit_code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue())["error"]["code"],
            "PLAN_CONFIRMATION_REQUIRED",
        )

    def test_exact_plan_confirmation_allows_over_threshold_run(self) -> None:
        config = private_config()
        config["companies"].append({
            "id": "beta",
            "name": "第二家公司",
            "location": {"address": "示例市公司路 2 號"},
        })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            dependency_info = dependency()
            dependency_info["path"] = str(google_routes.resolve())
            plan = commute_analyzer.build_plan(
                {"schema_version": "1"},
                config,
                dependency_info,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )
            calls: list[str] = []

            def dependency_runner(
                skill_path: Path,
                command: str,
                payload: object,
                environ: dict[str, str],
            ) -> tuple[int, str, str]:
                del skill_path, environ
                calls.append(command)
                if command == "capabilities":
                    return 0, json.dumps(self._compatible_capabilities()), ""
                return 0, json.dumps(route_result_for_plan(plan)), ""

            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                [
                    "run",
                    "--confirm-plan-id",
                    plan["plan_id"],
                    "--output-dir",
                    str(root / "reports"),
                ],
                stdin=io.StringIO(json.dumps(plan)),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "GOOGLE_MAPS_API_KEY": "test-only-key",
                    "GOOGLE_ROUTES_SKILL_DIR": str(google_routes),
                    "XDG_DATA_HOME": str(root / "data"),
                },
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["capabilities", "query"])
        self.assertEqual(json.loads(stdout.getvalue())["request_summary"]["planned"], 40)

    def test_missing_api_key_stops_before_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            dependency_info = dependency()
            dependency_info["path"] = str(google_routes.resolve())
            plan = commute_analyzer.build_plan(
                {"schema_version": "1"},
                private_config(),
                dependency_info,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )
            calls: list[str] = []

            def dependency_runner(
                skill_path: Path,
                command: str,
                payload: object,
                environ: dict[str, str],
            ) -> tuple[int, str, str]:
                del skill_path, payload, environ
                calls.append(command)
                return 0, json.dumps(self._compatible_capabilities()), ""

            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                ["run"],
                stdin=io.StringIO(json.dumps(plan)),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"GOOGLE_ROUTES_SKILL_DIR": str(google_routes)},
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, ["capabilities"])
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "MISSING_API_KEY")

    def test_run_does_not_execute_dependency_path_supplied_only_by_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            untrusted = root / "untrusted" / "google-routes"
            DependencyTests._make_skill(untrusted)
            dependency_info = dependency()
            dependency_info["path"] = str(untrusted.resolve())
            plan = commute_analyzer.build_plan(
                {"schema_version": "1"},
                private_config(),
                dependency_info,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )
            calls: list[str] = []

            def dependency_runner(
                skill_path: Path,
                command: str,
                payload: object,
                environ: dict[str, str],
            ) -> tuple[int, str, str]:
                del skill_path, command, payload, environ
                calls.append("executed")
                return 0, "{}", ""

            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                ["run"],
                stdin=io.StringIO(json.dumps(plan)),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"GOOGLE_MAPS_API_KEY": "test-only-key"},
                cwd=root / "project",
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, [])
        self.assertEqual(
            json.loads(stdout.getvalue())["error"]["code"],
            "PLAN_DEPENDENCY_CHANGED",
        )

    def test_motorcycle_failure_excludes_company_but_drive_failure_does_not(self) -> None:
        config = private_config()
        config["companies"].append({
            "id": "beta",
            "name": "第二家公司",
            "location": {"address": "示例市公司路 2 號"},
        })
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            config,
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        acme_motorcycle = next(
            sample["request_id"]
            for sample in plan["samples"]
            if sample["company_id"] == "acme" and sample["travel_mode"] == "TWO_WHEELER"
        )
        beta_drive = next(
            sample["request_id"]
            for sample in plan["samples"]
            if sample["company_id"] == "beta" and sample["travel_mode"] == "DRIVE"
        )
        result = commute_analyzer.analyze_route_results(
            plan,
            route_result_for_plan(
                plan,
                {
                    acme_motorcycle: {"status": "error"},
                    beta_drive: {"status": "error"},
                },
            ),
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )

        by_id = {company["company_id"]: company for company in result["companies"]}
        self.assertFalse(by_id["acme"]["ranking_eligible"])
        self.assertTrue(by_id["beta"]["ranking_eligible"])
        self.assertEqual([item["company_id"] for item in result["ranking"]], ["beta"])
        self.assertEqual(result["status"], "partial_success")

    def test_multi_week_results_are_normalized_to_one_week(self) -> None:
        plan = commute_analyzer.build_plan(
            {
                "schema_version": "1",
                "start_date": "2026-09-13",
                "weeks": 2,
                "weekdays": [2, 4],
            },
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        result = commute_analyzer.analyze_route_results(
            plan,
            route_result_for_plan(plan),
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )
        motorcycle = result["companies"][0]["modes"]["TWO_WHEELER"]

        self.assertEqual(motorcycle["weekly_total_seconds"], 2400)
        self.assertEqual(motorcycle["four_week_month_estimate_seconds"], 9600)

    def test_motorcycle_fallback_is_not_counted_as_a_required_success(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        request_id = next(
            sample["request_id"]
            for sample in plan["samples"]
            if sample["travel_mode"] == "TWO_WHEELER"
        )
        result = commute_analyzer.analyze_route_results(
            plan,
            route_result_for_plan(
                plan,
                {
                    request_id: {
                        "status": "degraded",
                        "fallback": {"routing_mode": "FALLBACK", "reason": "LATENCY"},
                    }
                },
            ),
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )

        self.assertFalse(result["companies"][0]["ranking_eligible"])
        self.assertEqual(result["request_summary"]["degraded"], 1)

    def test_provider_error_is_sanitized_before_report_data(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        request_id = plan["samples"][0]["request_id"]
        route_result = route_result_for_plan(plan, {request_id: {"status": "error"}})
        provider_error = route_result["results"][0]["error"]
        provider_error["message"] = "failed near 示例市住家路 1 號"
        provider_error["private_debug"] = "secret detail"

        result = commute_analyzer.analyze_route_results(
            plan,
            route_result,
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertNotIn("示例市住家路", serialized)
        self.assertNotIn("secret detail", serialized)
        self.assertEqual(
            result["companies"][0]["modes"]["TWO_WHEELER"]["samples"][0]["error"],
            {"code": "NETWORK_ERROR", "retryable": True},
        )

    def test_provider_result_must_match_planned_mode(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        route_result = route_result_for_plan(plan)
        route_result["results"][0]["travel_mode"] = "DRIVE"

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.analyze_route_results(
                plan,
                route_result,
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "GOOGLE_ROUTES_RESULT_INCOMPATIBLE")


class PrivatePathTests(unittest.TestCase):
    def test_default_paths_follow_each_operating_system_convention(self) -> None:
        windows = commute_analyzer.default_private_paths(
            platform_name="win32",
            environ={"APPDATA": "C:/Roaming", "LOCALAPPDATA": "C:/Local"},
            home=Path("C:/Users/example"),
        )
        macos = commute_analyzer.default_private_paths(
            platform_name="darwin", environ={}, home=Path("/Users/example")
        )
        linux = commute_analyzer.default_private_paths(
            platform_name="linux",
            environ={"XDG_CONFIG_HOME": "/cfg", "XDG_DATA_HOME": "/data"},
            home=Path("/home/example"),
        )

        self.assertEqual(windows["config"], Path("C:/Roaming/command1264-skills/commute-analyzer/config.json"))
        self.assertEqual(windows["reports"], Path("C:/Local/command1264-skills/commute-analyzer/reports"))
        self.assertEqual(macos["config"], Path("/Users/example/Library/Application Support/command1264-skills/commute-analyzer/config.json"))
        self.assertEqual(linux["ledger"], Path("/data/command1264-skills/commute-analyzer/usage.jsonl"))


class ExampleTests(unittest.TestCase):
    def test_result_example_matches_runtime_analysis_and_has_no_locations(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        plan = json.loads((examples / "plan.json").read_text(encoding="utf-8"))
        expected = json.loads((examples / "result.json").read_text(encoding="utf-8"))
        route_result = route_result_for_plan(plan)
        for result in route_result["results"]:
            duration = 600 if result["travel_mode"] == "TWO_WHEELER" else 900
            result["duration_seconds"] = duration
            result["static_duration_seconds"] = duration - 60
        actual = commute_analyzer.analyze_route_results(
            plan,
            route_result,
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )
        actual["outputs"] = expected["outputs"]

        self.assertEqual(actual, expected)
        serialized = json.dumps(expected)
        self.assertNotIn("Example Road", serialized)
        self.assertNotIn("ChIJExampleCompany", serialized)


if __name__ == "__main__":
    unittest.main()
