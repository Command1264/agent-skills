from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "google-routes" / "scripts" / "google_routes.py"
SPEC = importlib.util.spec_from_file_location("google_routes", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
google_routes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(google_routes)


def route_request(
    request_id: str = "route-1", travel_mode: str = "DRIVE"
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "origin": {"address": "示例市起點路 1 號"},
        "destination": {"place_id": "ChIJExampleDestination"},
        "travel_mode": travel_mode,
        "departure_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }


def batch(*requests: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1",
        "profile": "summary",
        "rate_limit_qpm": 60,
        "requests": list(requests or (route_request(),)),
    }


def provider_success(*, fallback: bool = False) -> dict[str, object]:
    response: dict[str, object] = {
        "routes": [
            {
                "distanceMeters": 12345,
                "duration": "1250.5s",
                "staticDuration": "1100s",
                "warnings": ["示例警告"],
            }
        ],
        "geocodingResults": {
            "origin": {"placeId": "ChIJResolvedOrigin"},
        },
    }
    if fallback:
        response["fallbackInfo"] = {
            "routingMode": "FALLBACK_TRAFFIC_AWARE",
            "reason": "LATENCY_EXCEEDED",
        }
    return response


class FakeTransport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def send(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout_seconds: float,
    ) -> object:
        self.calls.append(
            {"url": url, "headers": headers, "body": body, "timeout": timeout_seconds}
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class StepClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class ContractTests(unittest.TestCase):
    def test_capabilities_does_not_require_api_key(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = google_routes.run(
            ["capabilities"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=stderr,
            environ={},
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["skill_version"], "1.0.0")
        self.assertEqual(result["cli_contract_version"], "1.0.0")
        self.assertEqual(result["schema_versions"], ["1"])
        self.assertEqual(result["travel_modes"], ["DRIVE", "TWO_WHEELER"])
        self.assertEqual(result["output_profiles"], ["summary"])

    def test_unknown_field_reports_precise_json_path(self) -> None:
        payload = batch()
        payload["unexpected"] = True

        with self.assertRaises(google_routes.InputError) as context:
            google_routes.validate_batch(payload)

        self.assertEqual(context.exception.path, "$.unexpected")

    def test_location_requires_exactly_one_supported_field(self) -> None:
        payload = batch()
        payload["requests"][0]["origin"] = {
            "address": "示例市起點路 1 號",
            "place_id": "ChIJUnexpected",
        }

        with self.assertRaises(google_routes.InputError) as context:
            google_routes.validate_batch(payload)

        self.assertEqual(context.exception.path, "$.requests[0].origin")

    def test_duplicate_request_ids_are_rejected(self) -> None:
        with self.assertRaises(google_routes.InputError) as context:
            google_routes.validate_batch(batch(route_request(), route_request()))

        self.assertEqual(context.exception.path, "$.requests[1].request_id")

    def test_request_id_cannot_contain_sensitive_free_form_text(self) -> None:
        payload = batch(route_request("home to office"))

        with self.assertRaises(google_routes.InputError) as context:
            google_routes.validate_batch(payload)

        self.assertEqual(context.exception.path, "$.requests[0].request_id")


class ProviderMappingTests(unittest.TestCase):
    def test_drive_uses_optimal_best_guess_and_minimal_field_mask(self) -> None:
        transport = FakeTransport(
            [google_routes.HttpResponse(200, provider_success(), {})]
        )

        output, exit_code = google_routes.execute_batch(
            batch(route_request(travel_mode="DRIVE")),
            api_key="test-key-not-a-real-secret",
            transport=transport,
        )

        self.assertEqual(exit_code, 0)
        sent = transport.calls[0]
        self.assertEqual(sent["url"], google_routes.ROUTES_ENDPOINT)
        self.assertEqual(sent["headers"]["X-Goog-Api-Key"], "test-key-not-a-real-secret")
        self.assertEqual(sent["headers"]["X-Goog-FieldMask"], google_routes.FIELD_MASK)
        self.assertNotIn("test-key-not-a-real-secret", json.dumps(output))
        self.assertEqual(sent["body"]["routingPreference"], "TRAFFIC_AWARE_OPTIMAL")
        self.assertEqual(sent["body"]["trafficModel"], "BEST_GUESS")
        self.assertEqual(sent["body"]["origin"], {"address": "示例市起點路 1 號"})
        self.assertEqual(
            sent["body"]["destination"], {"placeId": "ChIJExampleDestination"}
        )

    def test_two_wheeler_uses_traffic_aware_without_traffic_model(self) -> None:
        transport = FakeTransport(
            [google_routes.HttpResponse(200, provider_success(), {})]
        )

        google_routes.execute_batch(
            batch(route_request(travel_mode="TWO_WHEELER")),
            api_key="test-key-not-a-real-secret",
            transport=transport,
        )

        sent_body = transport.calls[0]["body"]
        self.assertEqual(sent_body["routingPreference"], "TRAFFIC_AWARE")
        self.assertNotIn("trafficModel", sent_body)

    def test_summary_normalizes_duration_place_ids_and_fallback(self) -> None:
        transport = FakeTransport(
            [google_routes.HttpResponse(200, provider_success(fallback=True), {})]
        )

        output, exit_code = google_routes.execute_batch(
            batch(), api_key="test-key-not-a-real-secret", transport=transport
        )

        self.assertEqual(exit_code, 3)
        self.assertEqual(output["status"], "degraded")
        result = output["results"][0]
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["distance_meters"], 12345)
        self.assertEqual(result["duration_seconds"], 1250.5)
        self.assertEqual(result["static_duration_seconds"], 1100)
        self.assertEqual(result["origin_place_id"], "ChIJResolvedOrigin")
        self.assertEqual(result["destination_place_id"], "ChIJExampleDestination")
        self.assertEqual(result["warnings"], ["示例警告"])
        self.assertEqual(
            result["fallback"],
            {
                "routing_mode": "FALLBACK_TRAFFIC_AWARE",
                "reason": "LATENCY_EXCEEDED",
            },
        )
        self.assertNotIn("routes", result)

    def test_invalid_success_response_becomes_per_item_error(self) -> None:
        transport = FakeTransport([google_routes.HttpResponse(200, {}, {})])

        output, exit_code = google_routes.execute_batch(
            batch(), api_key="test-key-not-a-real-secret", transport=transport
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(
            output["results"][0]["error"]["code"], "invalid_provider_response"
        )


class RetryAndBatchTests(unittest.TestCase):
    def test_429_honors_retry_after_and_retries_at_most_twice(self) -> None:
        clock = StepClock()
        transport = FakeTransport(
            [
                google_routes.HttpResponse(429, {"error": {}}, {"Retry-After": "2"}),
                google_routes.HttpResponse(503, {"error": {}}, {}),
                google_routes.HttpResponse(200, provider_success(), {}),
            ]
        )

        output, exit_code = google_routes.execute_batch(
            batch(),
            api_key="test-key-not-a-real-secret",
            transport=transport,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(transport.calls), 3)
        self.assertIn(2.0, clock.sleeps)
        self.assertEqual(output["results"][0]["attempts"], 3)

    def test_network_failure_retries_twice_then_stops(self) -> None:
        clock = StepClock()
        transport = FakeTransport(
            [
                google_routes.NetworkTransportError(),
                google_routes.NetworkTransportError(),
                google_routes.NetworkTransportError(),
            ]
        )

        output, exit_code = google_routes.execute_batch(
            batch(),
            api_key="test-key-not-a-real-secret",
            transport=transport,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(output["results"][0]["attempts"], 3)
        self.assertEqual(output["results"][0]["error"]["code"], "network_error")

    def test_5xx_retries_twice_then_stops(self) -> None:
        clock = StepClock()
        transport = FakeTransport(
            [google_routes.HttpResponse(503, {}, {}) for _ in range(3)]
        )

        output, exit_code = google_routes.execute_batch(
            batch(),
            api_key="test-key-not-a-real-secret",
            transport=transport,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(output["results"][0]["error"]["http_status"], 503)

    def test_zero_retry_mode_hard_caps_one_attempt_per_item(self) -> None:
        transport = FakeTransport(
            [google_routes.HttpResponse(503, {}, {})]
        )

        output, exit_code = google_routes.execute_batch(
            batch(),
            api_key="test-key-not-a-real-secret",
            transport=transport,
            max_retries=0,
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(output["results"][0]["attempts"], 1)


class ExampleTests(unittest.TestCase):
    def test_query_example_matches_runtime_contract(self) -> None:
        example_path = ROOT / "skills" / "google-routes" / "examples" / "query.json"
        payload = json.loads(example_path.read_text(encoding="utf-8"))

        validated = google_routes.validate_batch(payload)

        self.assertEqual(validated["schema_version"], "1")

    def test_result_example_has_only_summary_fields(self) -> None:
        example_path = ROOT / "skills" / "google-routes" / "examples" / "result.json"
        payload = json.loads(example_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "1")
        self.assertNotIn("routes", json.dumps(payload))
        self.assertNotIn("polyline", json.dumps(payload))

    def test_smoke_runner_refuses_without_explicit_opt_in(self) -> None:
        script = ROOT / "skills" / "google-routes" / "scripts" / "smoke_test.py"
        example = ROOT / "skills" / "google-routes" / "examples" / "query.json"

        completed = subprocess.run(
            [sys.executable, str(script), str(example)],
            cwd=ROOT,
            env={key: value for key, value in os.environ.items() if key != "GOOGLE_MAPS_API_KEY"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--confirm-billable-smoke", completed.stderr)


class ErrorAndCliTests(unittest.TestCase):

    def test_ordinary_4xx_is_not_retried(self) -> None:
        transport = FakeTransport(
            [google_routes.HttpResponse(400, {"error": {"status": "INVALID_ARGUMENT"}}, {})]
        )

        output, exit_code = google_routes.execute_batch(
            batch(), api_key="test-key-not-a-real-secret", transport=transport
        )

        self.assertEqual(exit_code, 4)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(output["results"][0]["error"]["code"], "INVALID_ARGUMENT")

    def test_batch_preserves_success_when_another_request_fails(self) -> None:
        clock = StepClock()
        transport = FakeTransport(
            [
                google_routes.HttpResponse(200, provider_success(), {}),
                google_routes.HttpResponse(404, {"error": {"status": "NOT_FOUND"}}, {}),
            ]
        )

        output, exit_code = google_routes.execute_batch(
            batch(route_request("ok"), route_request("bad")),
            api_key="test-key-not-a-real-secret",
            transport=transport,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(exit_code, 3)
        self.assertEqual(output["status"], "partial_success")
        self.assertEqual([item["request_id"] for item in output["results"]], ["ok", "bad"])
        self.assertEqual([item["status"] for item in output["results"]], ["success", "error"])

    def test_query_requires_environment_key_without_echoing_it(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = google_routes.run(
            ["query"],
            stdin=io.StringIO(json.dumps(batch())),
            stdout=stdout,
            stderr=stderr,
            environ={},
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "missing_api_key")
        self.assertIn("GOOGLE_MAPS_API_KEY", stderr.getvalue())

    def test_query_writes_only_json_to_stdout_and_diagnostics_to_stderr(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        transport = FakeTransport(
            [google_routes.HttpResponse(200, provider_success(), {})]
        )

        exit_code = google_routes.run(
            ["query"],
            stdin=io.StringIO(json.dumps(batch())),
            stdout=stdout,
            stderr=stderr,
            environ={"GOOGLE_MAPS_API_KEY": "test-key-not-a-real-secret"},
            transport=transport,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "success")
        self.assertNotIn("完成", stdout.getvalue())
        self.assertIn("路線批次完成", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
