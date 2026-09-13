from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
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


class CliEncodingTests(unittest.TestCase):
    def test_plan_cli_forces_utf8_when_parent_pipe_encoding_is_cp950(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        completed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "plan",
                "--config",
                str(examples / "config-v2.json"),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "cp950:surrogateescape"},
            input=(examples / "plan-request-v2.json").read_bytes(),
            capture_output=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", errors="replace"),
        )
        result = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(result["schema_version"], "2")
        self.assertEqual(result["preview"]["journey_count"], 2)


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


def itinerary_dependency() -> dict[str, object]:
    return {
        "path": "/opt/skills/google-routes",
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


def itinerary_capabilities() -> dict[str, object]:
    return {
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


def route_result_for_plan(
    plan: dict[str, object], overrides: dict[str, dict[str, object]] | None = None
) -> dict[str, object]:
    replacements = overrides or {}
    results: list[dict[str, object]] = []
    for sample in plan["samples"]:
        points = sample["points"]
        leg_count = len(points) - 1
        result: dict[str, object] = {
            "request_id": sample["request_id"],
            "status": "success",
            "travel_mode": sample["travel_mode"],
            "distance_meters": 10000 * leg_count,
            "duration_seconds": 600,
            "static_duration_seconds": 540,
            "warnings": [],
            "fallback": None,
            "points": [
                {"label": point["label"], "place_id": None}
                for point in points
            ],
            "legs": [
                {
                    "from_label": points[index]["label"],
                    "to_label": points[index + 1]["label"],
                    "distance_meters": 10000,
                    "duration_seconds": 600 / leg_count,
                    "static_duration_seconds": 540 / leg_count,
                }
                for index in range(leg_count)
            ],
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
        "schema_version": "2",
        "cli_contract_version": "2.0.0",
        "profile": "itinerary_summary",
        "status": "success",
        "results": results,
    }


class CapabilitiesTests(unittest.TestCase):
    def test_capabilities_is_offline_and_describes_v2_planning_contract(self) -> None:
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
                "skill_version": "2.0.0",
                "cli_contract_version": "2.0.0",
                "config_schema_versions": ["1", "2"],
                "plan_request_schema_versions": ["1", "2"],
                "plan_schema_versions": ["2"],
                "result_schema_versions": ["2"],
                "commands": [
                    "capabilities",
                    "config path",
                    "config check",
                    "plan",
                    "run",
                ],
                "required_google_routes": {
                    "skill_major": 2,
                    "cli_contract_version": "2.0.0",
                    "schema_version": "2",
                    "output_profile": "itinerary_summary",
                    "minimum_points": 2,
                    "maximum_points": 12,
                    "maximum_intermediate_waypoints": 10,
                    "waypoint_order": "fixed",
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
            "npx skills add Command1264/agent-skills",
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

    def test_accepts_fixed_order_itinerary_capabilities(self) -> None:
        capability_value = {
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

        actual = commute_analyzer.validate_google_routes_capabilities(
            capability_value, Path("C:/skills/google-routes")
        )

        self.assertEqual(
            actual,
            {
                "path": str(Path("C:/skills/google-routes").resolve()),
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
            },
        )

    def test_rejects_dependency_without_fixed_order_itinerary_contract(self) -> None:
        capability_value = {
            "skill_name": "google-routes",
            "skill_version": "2.1.0",
            "cli_contract_version": "2.0.0",
            "schema_versions": ["1", "2"],
            "travel_modes": ["DRIVE", "TWO_WHEELER"],
            "output_profiles": ["summary"],
            "itinerary_limits": {
                "minimum_points": 2,
                "maximum_points": 12,
                "maximum_intermediate_waypoints": 10,
                "waypoint_order": "optimized",
            },
        }

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_google_routes_capabilities(
                capability_value, Path("C:/skills/google-routes")
            )

        self.assertEqual(context.exception.code, "GOOGLE_ROUTES_INCOMPATIBLE")
        self.assertNotIn("C:/skills", context.exception.message)

    def test_google_routes_v1_is_rejected_before_planning(self) -> None:
        capabilities = {
            "skill_name": "google-routes",
            "skill_version": "1.0.0",
            "cli_contract_version": "1.0.0",
            "schema_versions": ["1"],
            "travel_modes": ["DRIVE", "TWO_WHEELER"],
            "output_profiles": ["summary"],
        }

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_google_routes_capabilities(
                capabilities, Path("C:/skills/google-routes")
            )

        self.assertEqual(context.exception.code, "GOOGLE_ROUTES_INCOMPATIBLE")
        self.assertIn("major 必須是 2", context.exception.message)

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
    @staticmethod
    def _v2_inputs() -> tuple[dict[str, object], dict[str, object]]:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        config = json.loads((examples / "config-v2.json").read_text(encoding="utf-8"))
        request = json.loads(
            (examples / "plan-request-v2.json").read_text(encoding="utf-8")
        )
        return config, request

    def test_v2_examples_reproduce_the_checked_in_plan_without_mutating_config(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        config, request = self._v2_inputs()
        expected = json.loads(
            (examples / "plan-v2.json").read_text(encoding="utf-8")
        )
        original_config = copy.deepcopy(config)
        original_request = copy.deepcopy(request)
        dependency_value = itinerary_dependency()

        actual = commute_analyzer.build_plan(
            request,
            config,
            dependency_value,
            now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(actual, expected)
        self.assertEqual(config, original_config)
        self.assertEqual(request, original_request)
        dependency_value["itinerary_limits"]["maximum_points"] = 99
        self.assertEqual(actual["dependency"]["itinerary_limits"]["maximum_points"], 12)
        self.assertEqual(
            commute_analyzer.validate_execution_plan(
                actual,
                now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
            ),
            actual,
        )

    def test_v2_preview_contains_labels_but_no_locations(self) -> None:
        config, request = self._v2_inputs()

        plan = commute_analyzer.build_plan(
            request,
            config,
            itinerary_dependency(),
            now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        preview = json.dumps(plan["preview"], ensure_ascii=False)

        self.assertIn("示例應徵公司", preview)
        self.assertNotIn("示例市第三路 3 號", preview)
        self.assertNotIn("ChIJExampleSchool", preview)
        self.assertNotIn('"location"', preview)

    def test_v2_accepts_twelve_fixed_order_points_and_expands_reverse(self) -> None:
        config, request = self._v2_inputs()
        points = [
            {
                "label": f"停靠點 {index}",
                "location": {"address": f"示例市測試路 {index} 號"},
            }
            for index in range(1, 13)
        ]
        request["journeys"] = [
            {
                "id": "twelve-points",
                "label": "十二點固定路線",
                "outbound": {"points": points},
                "return": {"reverse_outbound": True},
            }
        ]

        plan = commute_analyzer.build_plan(
            request,
            config,
            itinerary_dependency(),
            now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["samples"][0]["points"], points)
        self.assertEqual(plan["samples"][1]["points"], list(reversed(points)))
        self.assertEqual(plan["samples"][0]["expected_leg_count"], 11)

    def test_v2_rejects_thirteen_points(self) -> None:
        config, request = self._v2_inputs()
        request["journeys"][0]["outbound"]["points"] = [
            {
                "label": f"停靠點 {index}",
                "location": {"address": f"示例市測試路 {index} 號"},
            }
            for index in range(1, 14)
        ]

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.build_plan(
                request,
                config,
                itinerary_dependency(),
                now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_INPUT")
        self.assertEqual(context.exception.path, "$.journeys[0].outbound.points")

    def test_v2_rejects_cross_version_inputs(self) -> None:
        config_v2, request_v2 = self._v2_inputs()
        cases = [
            (private_config(), request_v2),
            (config_v2, {"schema_version": "1"}),
        ]

        for config, request in cases:
            with self.subTest(config_version=config["schema_version"]):
                with self.assertRaises(commute_analyzer.InputError) as context:
                    commute_analyzer.build_plan(
                        request,
                        config,
                        itinerary_dependency(),
                        now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
                    )
                self.assertEqual(
                    context.exception.code,
                    "INCOMPATIBLE_INPUT_SCHEMA_VERSIONS",
                )
                self.assertEqual(context.exception.path, "$.schema_version")

    def test_v2_rejects_ambiguous_or_unknown_journey_references(self) -> None:
        config, request = self._v2_inputs()
        cases: list[tuple[str, dict[str, object], dict[str, object], str, str]] = []

        duplicate_locations = copy.deepcopy(config)
        duplicate_locations["locations"].append(copy.deepcopy(config["locations"][0]))
        cases.append(
            (
                "duplicate location",
                duplicate_locations,
                request,
                "DUPLICATE_LOCATION_ID",
                "$config.locations[3].id",
            )
        )

        unknown_location = copy.deepcopy(request)
        unknown_location["journeys"][0]["outbound"]["points"][0] = {
            "location_id": "missing"
        }
        cases.append(
            (
                "unknown location",
                config,
                unknown_location,
                "UNKNOWN_LOCATION_ID",
                "$.journeys[0].outbound.points[0].location_id",
            )
        )

        duplicate_journey = copy.deepcopy(request)
        duplicate_journey["journeys"].append(copy.deepcopy(request["journeys"][0]))
        cases.append(
            (
                "duplicate journey",
                config,
                duplicate_journey,
                "DUPLICATE_JOURNEY_ID",
                "$.journeys[2].id",
            )
        )

        duplicate_label = copy.deepcopy(request)
        duplicate_label["journeys"][0]["outbound"]["points"][1]["label"] = (
            "示例住家"
        )
        cases.append(
            (
                "duplicate label",
                config,
                duplicate_label,
                "DUPLICATE_POINT_LABEL",
                "$.journeys[0].outbound.points[1].label",
            )
        )

        ambiguous_return = copy.deepcopy(request)
        ambiguous_return["journeys"][0]["return"] = {
            "reverse_outbound": True,
            "points": copy.deepcopy(request["journeys"][0]["outbound"]["points"]),
        }
        cases.append(
            (
                "ambiguous return",
                config,
                ambiguous_return,
                "INVALID_RETURN_DEFINITION",
                "$.journeys[0].return",
            )
        )

        for name, case_config, case_request, code, path in cases:
            with self.subTest(name=name):
                with self.assertRaises(commute_analyzer.InputError) as context:
                    commute_analyzer.build_plan(
                        case_request,
                        case_config,
                        itinerary_dependency(),
                        now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
                    )
                self.assertEqual(context.exception.code, code)
                self.assertEqual(context.exception.path, path)

    def test_v1_adapter_rejects_incompatible_label_at_original_path(self) -> None:
        config = private_config()
        config["home"]["label"] = "住" * 81

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.build_plan(
                {"schema_version": "1"},
                config,
                itinerary_dependency(),
                now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "LEGACY_POINT_LABEL_INCOMPATIBLE")
        self.assertEqual(context.exception.path, "$config.home.label")

    def test_v1_inputs_are_adapted_to_the_single_v2_journey_plan(self) -> None:
        plan = commute_analyzer.build_plan(
            {
                "schema_version": "1",
                "start_date": "2099-01-05",
                "weekdays": [1],
                "travel_modes": ["TWO_WHEELER"],
                "additional_companies": [
                    {
                        "id": "beta",
                        "name": "第二家公司",
                        "location": {"address": "範例市公司路 2 號"},
                    }
                ],
            },
            private_config(),
            itinerary_dependency(),
            now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["schema_version"], "2")
        self.assertEqual(
            plan["input_compatibility"],
            {
                "config_schema_version": "1",
                "plan_request_schema_version": "1",
                "adapter": "v1_to_v2",
            },
        )
        self.assertEqual(plan["preview"]["journey_count"], 2)
        self.assertEqual(plan["preview"]["request_count"], 4)
        self.assertEqual(
            plan["samples"][0]["points"],
            [
                {"label": "home", "location": {"address": "示例市住家路 1 號"}},
                {
                    "label": "範例公司",
                    "location": {"place_id": "ChIJExampleCompany"},
                },
            ],
        )
        self.assertEqual(
            plan["samples"][1]["points"],
            list(reversed(plan["samples"][0]["points"])),
        )

    def test_v1_plan_is_rejected_and_must_be_regenerated(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        legacy_plan = json.loads((examples / "plan.json").read_text(encoding="utf-8"))

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                legacy_plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "LEGACY_PLAN_REQUIRES_REGENERATION")
        self.assertEqual(context.exception.path, "$.schema_version")

    def test_default_plan_expands_next_workweek_without_external_calls(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
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

    def test_plan_cli_accepts_v2_and_keeps_locations_out_of_diagnostics(self) -> None:
        calls: list[str] = []

        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path, payload, environ
            calls.append(command)
            return 0, json.dumps(itinerary_capabilities()), ""

        config, request = self._v2_inputs()
        config["locations"][0]["location"] = {
            "address": "不可出現在診斷的私人地址"
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["plan", "--config", str(config_path)],
                stdin=io.StringIO(json.dumps(request, ensure_ascii=False)),
                stdout=stdout,
                stderr=stderr,
                environ={"GOOGLE_ROUTES_SKILL_DIR": str(google_routes)},
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["capabilities"])
        self.assertEqual(json.loads(stdout.getvalue())["schema_version"], "2")
        self.assertNotIn("不可出現在診斷的私人地址", stderr.getvalue())

    def test_plan_uses_visible_legacy_windows_config_with_migration_warning(self) -> None:
        calls: list[str] = []

        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path, payload, environ
            calls.append(command)
            return 0, json.dumps(itinerary_capabilities()), ""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            legacy_config = (
                root
                / "legacy-roaming"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            legacy_config.parent.mkdir(parents=True)
            legacy_config.write_text(
                json.dumps(private_config(), ensure_ascii=False), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["plan"],
                stdin=io.StringIO('{"schema_version":"1"}'),
                stdout=stdout,
                stderr=stderr,
                environ={
                    "APPDATA": str(root / "legacy-roaming"),
                    "GOOGLE_ROUTES_SKILL_DIR": str(google_routes),
                },
                cwd=root,
                home=home,
                platform_name="win32",
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["capabilities"])
        self.assertEqual(json.loads(stdout.getvalue())["preview"]["request_count"], 20)
        self.assertIn("legacy_windows_appdata_path", stderr.getvalue())
        self.assertIn("人工移至", stderr.getvalue())

    def test_modified_plan_is_rejected_before_execution(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
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
            itinerary_dependency(),
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
            itinerary_dependency(),
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

    def test_rehashed_plan_with_incomplete_sample_matrix_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["samples"].pop()
        plan["preview"]["request_count"] -= 1
        plan["preview"]["maximum_http_requests"] -= 3
        plan["preview"]["estimated_sku_requests"]["routes_compute_pro"] -= 1
        plan["preview"]["planned_leg_count"] -= 1
        content = {key: value for key, value in plan.items() if key != "plan_id"}
        plan["plan_id"] = commute_analyzer._content_id(content)

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_PLAN")
        self.assertEqual(context.exception.path, "$.samples")

    def test_rehashed_plan_with_departure_outside_schedule_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["samples"][0]["departure_time"] = "2026-09-14T09:00:00+08:00"
        content = {key: value for key, value in plan.items() if key != "plan_id"}
        plan["plan_id"] = commute_analyzer._content_id(content)

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_PLAN")
        self.assertEqual(context.exception.path, "$.samples[0].departure_time")

    def test_rehashed_plan_with_invalid_created_at_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        plan["created_at"] = "not-a-date"
        content = {key: value for key, value in plan.items() if key != "plan_id"}
        plan["plan_id"] = commute_analyzer._content_id(content)

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.validate_execution_plan(
                plan,
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "INVALID_PLAN")
        self.assertEqual(context.exception.path, "$.created_at")

    def test_expired_plan_is_rejected(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1"},
            private_config(),
            itinerary_dependency(),
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
            itinerary_dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(plan["schedule"]["dates"], [
            "2026-09-15",
            "2026-09-17",
            "2026-09-22",
            "2026-09-24",
        ])
        self.assertEqual(plan["preview"]["journey_count"], 2)
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
        return itinerary_capabilities()

    def test_legacy_plan_stops_before_dependency_or_private_output(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        legacy_plan = (examples / "plan.json").read_text(encoding="utf-8")
        calls: list[str] = []

        def dependency_runner(
            skill_path: Path,
            command: str,
            payload: object,
            environ: dict[str, str],
        ) -> tuple[int, str, str]:
            del skill_path, payload, environ
            calls.append(command)
            self.fail("plan v1 不得接觸 dependency")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "reports"
            stdout = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["run", "--output-dir", str(output_dir)],
                stdin=io.StringIO(legacy_plan),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={},
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(calls, [])
        self.assertFalse(output_dir.exists())
        self.assertEqual(
            json.loads(stdout.getvalue())["error"]["code"],
            "LEGACY_PLAN_REQUIRES_REGENERATION",
        )

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
                return 0, json.dumps(itinerary_capabilities()), ""
            self.assertNotIn("GOOGLE_MAPS_API_KEY", environ)
            self.assertEqual(payload["schema_version"], "2")
            self.assertEqual(payload["profile"], "itinerary_summary")
            requests = payload["requests"]
            results = []
            for request in requests:
                duration = {
                    ("outbound", "TWO_WHEELER"): 600,
                    ("outbound", "DRIVE"): 900,
                    ("return", "TWO_WHEELER"): 720,
                    ("return", "DRIVE"): 840,
                }[(request["request_id"].split(".")[2], request["travel_mode"])]
                points = request["points"]
                results.append({
                    "request_id": request["request_id"],
                    "status": "success",
                    "travel_mode": request["travel_mode"],
                    "distance_meters": 10000,
                    "duration_seconds": duration,
                    "static_duration_seconds": duration - 60,
                    "warnings": [],
                    "fallback": None,
                    "points": [
                        {"label": point["label"], "place_id": None}
                        for point in points
                    ],
                    "legs": [
                        {
                            "from_label": points[index]["label"],
                            "to_label": points[index + 1]["label"],
                            "distance_meters": 10000,
                            "duration_seconds": duration,
                            "static_duration_seconds": duration - 60,
                        }
                        for index in range(len(points) - 1)
                    ],
                    "attempts": 1,
                })
            return 0, json.dumps({
                "schema_version": "2",
                "cli_contract_version": "2.0.0",
                "profile": "itinerary_summary",
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
        motorcycle = result["journeys"][0]["modes"]["TWO_WHEELER"]
        self.assertEqual(motorcycle["statistics"]["daily_round_trip"]["average_seconds"], 1320)
        self.assertEqual(motorcycle["weekly_total_seconds"], 6600)
        self.assertEqual(motorcycle["four_week_month_estimate_seconds"], 26400)
        self.assertEqual(result["ranking"][0]["journey_id"], "acme")
        self.assertIn("去程：平均", report_text)
        self.assertIn("回程：平均", report_text)
        self.assertIn("每日來回：平均", report_text)
        self.assertIn("四週月估算", report_text)
        self.assertNotIn("示例市住家路", report_text)
        self.assertNotIn("示例市住家路", report_json_text)
        self.assertNotIn("ChIJExampleCompany", report_json_text)
        self.assertNotIn("test-only-key", ledger_text)
        self.assertNotIn("duration", ledger_text)

    def test_v2_run_compares_saved_origins_and_inline_destination_with_waypoint(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        config = json.loads((examples / "config-v2.json").read_text(encoding="utf-8"))
        request = json.loads(
            (examples / "plan-request-v2.json").read_text(encoding="utf-8")
        )
        observed_query: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            google_routes = root / "google-routes"
            DependencyTests._make_skill(google_routes)
            dependency_info = itinerary_dependency()
            dependency_info["path"] = str(google_routes.resolve())
            plan = commute_analyzer.build_plan(
                request,
                config,
                dependency_info,
                now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
            )

            def dependency_runner(
                skill_path: Path,
                command: str,
                payload: object,
                environ: dict[str, str],
            ) -> tuple[int, str, str]:
                del skill_path, environ
                if command == "capabilities":
                    return 0, json.dumps(itinerary_capabilities()), ""
                observed_query.update(payload)
                return 0, json.dumps(route_result_for_plan(plan)), ""

            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                ["run", "--output-dir", str(root / "reports")],
                stdin=io.StringIO(json.dumps(plan, ensure_ascii=False)),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "GOOGLE_ROUTES_SKILL_DIR": str(google_routes),
                    "XDG_DATA_HOME": str(root / "data"),
                },
                cwd=root,
                home=root / "home",
                platform_name="linux",
                now=datetime(2099, 1, 1, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )
            result = json.loads(stdout.getvalue())
            report_json = Path(result["outputs"]["json_report"]).read_text(
                encoding="utf-8"
            )
            ledger = Path(result["outputs"]["usage_ledger"]).read_text(
                encoding="utf-8"
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(observed_query["schema_version"], "2")
        self.assertEqual(observed_query["profile"], "itinerary_summary")
        query_by_id = {
            item["request_id"]: item for item in observed_query["requests"]
        }
        outbound = query_by_id["rental-via-school.20990105.outbound.two-wheeler"]
        returning = query_by_id["rental-via-school.20990105.return.two-wheeler"]
        self.assertEqual(
            [point["label"] for point in outbound["points"]],
            ["示例租屋處", "示例學校", "示例應徵公司"],
        )
        self.assertEqual(
            [point["label"] for point in returning["points"]],
            ["示例應徵公司", "示例租屋處"],
        )
        self.assertEqual(
            [journey["journey_id"] for journey in result["journeys"]],
            ["home-to-candidate", "rental-via-school"],
        )
        self.assertEqual(
            len(result["journeys"][1]["modes"]["TWO_WHEELER"]["samples"][0]["legs"]),
            2,
        )
        for private_value in (
            "示例市第一路 1 號",
            "示例市第三路 3 號",
            "ChIJExampleSchool",
        ):
            self.assertNotIn(private_value, report_json)
            self.assertNotIn(private_value, ledger)

    def test_provider_leg_labels_must_match_planned_point_order(self) -> None:
        config, request = PlanTests._v2_inputs()
        plan = commute_analyzer.build_plan(
            request,
            config,
            itinerary_dependency(),
            now=datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        route_result = route_result_for_plan(plan)
        route_result["results"][2]["legs"][0]["to_label"] = "錯誤停靠點"

        with self.assertRaises(commute_analyzer.InputError) as context:
            commute_analyzer.analyze_route_results(
                plan,
                route_result,
                now=datetime(2099, 1, 1, 12, 5, tzinfo=timezone.utc),
            )

        self.assertEqual(context.exception.code, "DEPENDENCY_LEG_MISMATCH")
        self.assertEqual(context.exception.path, "$route_result.results[2].legs[0]")
        self.assertNotIn("示例市", context.exception.message)

    def test_windows_default_outputs_use_cross_runtime_user_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
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

            def dependency_runner(
                skill_path: Path,
                command: str,
                payload: object,
                environ: dict[str, str],
            ) -> tuple[int, str, str]:
                del skill_path, payload, environ
                if command == "capabilities":
                    return 0, json.dumps(self._compatible_capabilities()), ""
                return 0, json.dumps(route_result_for_plan(plan)), ""

            stdout = io.StringIO()
            exit_code = commute_analyzer.run_cli(
                ["run"],
                stdin=io.StringIO(json.dumps(plan)),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "APPDATA": str(root / "legacy-roaming"),
                    "LOCALAPPDATA": str(root / "legacy-local"),
                    "GOOGLE_ROUTES_SKILL_DIR": str(google_routes),
                },
                cwd=root,
                home=home,
                platform_name="win32",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
                dependency_runner=dependency_runner,
            )
            outputs = json.loads(stdout.getvalue())["outputs"]
            expected_data = (
                home / ".local" / "share" / "command1264-skills" / "commute-analyzer"
            ).resolve()

            self.assertTrue(Path(outputs["json_report"]).is_relative_to(expected_data))
            self.assertTrue(Path(outputs["markdown_report"]).is_relative_to(expected_data))
            self.assertEqual(Path(outputs["usage_ledger"]), expected_data / "usage.jsonl")
            self.assertFalse((root / "legacy-local").exists())

        self.assertEqual(exit_code, 0)

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
            environ={},
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

    def test_dependency_credential_error_is_sanitized(self) -> None:
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
                if command == "capabilities":
                    return 0, json.dumps(self._compatible_capabilities()), ""
                return 2, json.dumps(
                    {
                        "schema_version": "1",
                        "error": {
                            "code": "credential_file_not_found",
                            "path": "$credential_file",
                            "message": "private credential detail",
                        },
                    }
                ), "private stderr detail"

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
        self.assertEqual(calls, ["capabilities", "query"])
        error = json.loads(stdout.getvalue())["error"]
        self.assertEqual(error["code"], "GOOGLE_ROUTES_EXECUTION_FAILED")
        self.assertNotIn("private credential detail", json.dumps(error))
        self.assertNotIn("private stderr detail", json.dumps(error))

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
                environ={},
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

    def test_motorcycle_failure_excludes_journey_but_drive_failure_does_not(self) -> None:
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
            if sample["journey_id"] == "acme" and sample["travel_mode"] == "TWO_WHEELER"
        )
        beta_drive = next(
            sample["request_id"]
            for sample in plan["samples"]
            if sample["journey_id"] == "beta" and sample["travel_mode"] == "DRIVE"
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

        by_id = {journey["journey_id"]: journey for journey in result["journeys"]}
        self.assertFalse(by_id["acme"]["ranking_eligible"])
        self.assertTrue(by_id["beta"]["ranking_eligible"])
        self.assertEqual([item["journey_id"] for item in result["ranking"]], ["beta"])
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
        motorcycle = result["journeys"][0]["modes"]["TWO_WHEELER"]

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

        self.assertFalse(result["journeys"][0]["ranking_eligible"])
        self.assertEqual(result["request_summary"]["degraded"], 1)

    def test_drive_only_report_explains_that_motorcycle_was_not_requested(self) -> None:
        plan = commute_analyzer.build_plan(
            {"schema_version": "1", "travel_modes": ["DRIVE"]},
            private_config(),
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        result = commute_analyzer.analyze_route_results(
            plan,
            route_result_for_plan(plan),
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = commute_analyzer.write_private_outputs(
                result,
                plan,
                output_dir=root / "reports",
                ledger_path=root / "data" / "usage.jsonl",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
            )
            report = Path(outputs["markdown_report"]).read_text(encoding="utf-8")

        self.assertEqual(
            result["journeys"][0]["ranking_exclusion_reasons"],
            ["未要求機車模式"],
        )
        self.assertIn("排名：不納入（未要求機車模式）", report)
        self.assertNotIn("機車必要樣本不完整", report)

    def test_markdown_report_escapes_user_controlled_journey_labels(self) -> None:
        config = private_config()
        config["companies"][0]["name"] = (
            "![probe](https://example.invalid/pixel)\n# injected"
        )
        plan = commute_analyzer.build_plan(
            {"schema_version": "1", "travel_modes": ["DRIVE"]},
            config,
            dependency(),
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
        result = commute_analyzer.analyze_route_results(
            plan,
            route_result_for_plan(plan),
            now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = commute_analyzer.write_private_outputs(
                result,
                plan,
                output_dir=root / "reports",
                ledger_path=root / "data" / "usage.jsonl",
                now=datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
            )
            report = Path(outputs["markdown_report"]).read_text(encoding="utf-8")

        self.assertNotIn("![probe](", report)
        self.assertNotIn("\n# injected", report)
        self.assertIn(r"\!\[probe\]\(https://example\.invalid/pixel\)", report)

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
            result["journeys"][0]["modes"]["TWO_WHEELER"]["samples"][0]["error"],
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
    def test_default_paths_are_cross_runtime_and_follow_platform_conventions(self) -> None:
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

        self.assertEqual(
            windows["config"],
            Path("C:/Users/example/.config/command1264-skills/commute-analyzer/config.json"),
        )
        self.assertEqual(
            windows["reports"],
            Path("C:/Users/example/.local/share/command1264-skills/commute-analyzer/reports"),
        )
        self.assertEqual(macos["config"], Path("/Users/example/Library/Application Support/command1264-skills/commute-analyzer/config.json"))
        self.assertEqual(linux["ledger"], Path("/data/command1264-skills/commute-analyzer/usage.jsonl"))


class ConfigCliTests(unittest.TestCase):
    def test_config_check_accepts_v2_without_returning_location_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            config_path = (
                home
                / ".config"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "2",
                        "locations": [
                            {
                                "id": "private-home",
                                "label": "不可輸出的私人標籤",
                                "location": {"address": "不可輸出的私人地址"},
                            }
                        ],
                        "utc_offset": "+08:00",
                        "outbound_departure_time": "08:00",
                        "return_departure_time": "18:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "check"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                environ={},
                home=home,
                platform_name="linux",
            )
            serialized = stdout.getvalue()
            result = json.loads(serialized)

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["schema_version"], "2")
        self.assertEqual(result["config"]["content_schema_version"], "2")
        self.assertEqual(
            result["config"]["schema_migration"],
            {
                "target_schema_version": "2",
                "recommended": False,
                "automatic": False,
            },
        )
        self.assertNotIn("不可輸出的私人標籤", serialized)
        self.assertNotIn("不可輸出的私人地址", serialized)

    def test_config_path_reports_cross_runtime_windows_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "path"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                environ={
                    "APPDATA": str(root / "legacy-roaming"),
                    "LOCALAPPDATA": str(root / "legacy-local"),
                },
                home=home,
                platform_name="win32",
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "schema_version": "1",
                "config": {
                    "path": str(
                        home
                        / ".config"
                        / "command1264-skills"
                        / "commute-analyzer"
                        / "config.json"
                    ),
                    "default_path": str(
                        home
                        / ".config"
                        / "command1264-skills"
                        / "commute-analyzer"
                        / "config.json"
                    ),
                    "source": "cross_runtime_default",
                    "configured": False,
                    "migration_required": False,
                    "legacy_path": str(
                        root
                        / "legacy-roaming"
                        / "command1264-skills"
                        / "commute-analyzer"
                        / "config.json"
                    ),
                    "warnings": [],
                },
            },
        )

    def test_config_path_uses_legacy_windows_file_without_copying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            legacy_path = (
                root
                / "legacy-roaming"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text("{}", encoding="utf-8")
            default_path = (
                home
                / ".config"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            stdout = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "path"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"APPDATA": str(root / "legacy-roaming")},
                home=home,
                platform_name="win32",
            )

            result = json.loads(stdout.getvalue())
            self.assertFalse(default_path.exists())
            self.assertTrue(legacy_path.is_file())

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            result["config"],
            {
                "path": str(legacy_path),
                "default_path": str(default_path),
                "source": "legacy_windows_appdata",
                "configured": True,
                "migration_required": True,
                "legacy_path": str(legacy_path),
                "warnings": [
                    {
                        "code": "legacy_windows_appdata_path",
                        "message": (
                            "目前使用舊 Windows AppData config；"
                            "請人工移至跨 runtime 預設路徑"
                        ),
                    }
                ],
            },
        )

    def test_config_path_prefers_cross_runtime_default_over_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            default_path = (
                home
                / ".config"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            legacy_path = (
                root
                / "legacy-roaming"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            for path in (default_path, legacy_path):
                path.parent.mkdir(parents=True)
                path.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "path"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"APPDATA": str(root / "legacy-roaming")},
                home=home,
                platform_name="win32",
            )
            config = json.loads(stdout.getvalue())["config"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(config["path"], str(default_path))
        self.assertEqual(config["source"], "cross_runtime_default")
        self.assertEqual(config["migration_required"], False)
        self.assertEqual(config["warnings"], [])

    def test_config_path_prefers_environment_override_over_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            override_path = root / "portable" / "commute.json"
            default_path = (
                home
                / ".config"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            legacy_path = (
                root
                / "legacy-roaming"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            for path in (override_path, default_path, legacy_path):
                path.parent.mkdir(parents=True)
                path.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "path"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "APPDATA": str(root / "legacy-roaming"),
                    "COMMUTE_ANALYZER_CONFIG": str(override_path),
                },
                home=home,
                platform_name="win32",
            )
            config = json.loads(stdout.getvalue())["config"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(config["path"], str(override_path))
        self.assertEqual(config["source"], "environment_override")
        self.assertEqual(config["migration_required"], False)
        self.assertEqual(config["warnings"], [])

    def test_config_check_validates_without_returning_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            config_path = (
                home
                / ".config"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(private_config(), ensure_ascii=False), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "check"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                environ={"APPDATA": str(root / "legacy-roaming")},
                home=home,
                platform_name="win32",
            )
            serialized = stdout.getvalue()
            result = json.loads(serialized)

        self.assertEqual(exit_code, 0)
        self.assertIn("私人通勤設定有效", stderr.getvalue())
        self.assertEqual(result["config"]["path"], str(config_path))
        self.assertEqual(result["config"]["source"], "cross_runtime_default")
        self.assertEqual(result["config"]["configured"], True)
        self.assertEqual(result["config"]["content_schema_version"], "1")
        self.assertEqual(
            result["config"]["schema_migration"],
            {
                "target_schema_version": "2",
                "recommended": True,
                "automatic": False,
            },
        )
        self.assertNotIn("示例市住家路", serialized)
        self.assertNotIn("ChIJExampleCompany", serialized)
        self.assertNotIn("companies", serialized)

    def test_config_check_missing_file_gives_cross_runtime_setup_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stdout = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "check"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"APPDATA": str(root / "legacy-roaming")},
                home=root / "home",
                platform_name="win32",
            )
            error = json.loads(stdout.getvalue())["error"]

        self.assertEqual(exit_code, 2)
        self.assertEqual(error["code"], "CONFIG_NOT_FOUND")
        self.assertEqual(error["path"], "$config")
        self.assertIn("config path", error["message"])
        self.assertIn("人工", error["message"])

    def test_config_check_validates_legacy_file_and_preserves_migration_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy_path = (
                root
                / "legacy-roaming"
                / "command1264-skills"
                / "commute-analyzer"
                / "config.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps(private_config(), ensure_ascii=False), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = commute_analyzer.run_cli(
                ["config", "check"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                environ={"APPDATA": str(root / "legacy-roaming")},
                home=root / "home",
                platform_name="win32",
            )
            config = json.loads(stdout.getvalue())["config"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(config["source"], "legacy_windows_appdata")
        self.assertEqual(config["migration_required"], True)
        self.assertEqual(
            [warning["code"] for warning in config["warnings"]],
            ["legacy_windows_appdata_path"],
        )
        self.assertIn("legacy_windows_appdata_path", stderr.getvalue())


class ExampleTests(unittest.TestCase):
    def test_v2_result_example_matches_runtime_analysis_and_has_no_locations(self) -> None:
        examples = ROOT / "skills" / "commute-analyzer" / "examples"
        plan = json.loads((examples / "plan-v2.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (examples / "result-v2.json").read_text(encoding="utf-8")
        )
        plan_samples = {sample["request_id"]: sample for sample in plan["samples"]}
        provider_results = []
        for journey in expected["journeys"]:
            for mode in journey["modes"].values():
                for sample in mode["samples"]:
                    planned = plan_samples[sample["request_id"]]
                    provider_results.append(
                        {
                            "request_id": sample["request_id"],
                            "status": sample["status"],
                            "travel_mode": sample["travel_mode"],
                            "distance_meters": sample["distance_meters"],
                            "duration_seconds": sample["duration_seconds"],
                            "static_duration_seconds": sample[
                                "static_duration_seconds"
                            ],
                            "warnings": sample["warnings"],
                            "fallback": sample["fallback"],
                            "points": [
                                {"label": point["label"], "place_id": None}
                                for point in planned["points"]
                            ],
                            "legs": sample["legs"],
                            "attempts": sample["attempts"],
                        }
                    )
        route_result = {
            "schema_version": "2",
            "cli_contract_version": "2.0.0",
            "profile": "itinerary_summary",
            "status": "success",
            "results": provider_results,
        }
        actual = commute_analyzer.analyze_route_results(
            plan,
            route_result,
            now=datetime(2099, 1, 5, 12, 0, tzinfo=timezone.utc),
        )
        actual["outputs"] = expected["outputs"]

        self.assertEqual(actual, expected)
        serialized = json.dumps(expected, ensure_ascii=False)
        self.assertNotIn("示例市第三路 3 號", serialized)
        self.assertNotIn("ChIJExampleSchool", serialized)
        self.assertNotIn('"location"', serialized)


if __name__ == "__main__":
    unittest.main()
