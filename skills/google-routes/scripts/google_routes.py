#!/usr/bin/env python3
"""Stable JSON CLI for Google Routes API Compute Routes."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import google_routes_credentials


SKILL_VERSION = "2.1.0"
CLI_CONTRACT_VERSION = "2.0.0"
SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = ("1", "2")
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join(
    (
        "routes.distanceMeters",
        "routes.duration",
        "routes.staticDuration",
        "routes.warnings",
        "fallbackInfo.routingMode",
        "fallbackInfo.reason",
        "geocodingResults.origin.placeId",
        "geocodingResults.destination.placeId",
    )
)
ITINERARY_FIELD_MASK = ",".join(
    (
        FIELD_MASK,
        "routes.legs.distanceMeters",
        "routes.legs.duration",
        "routes.legs.staticDuration",
        "geocodingResults.intermediates.intermediateWaypointRequestIndex",
        "geocodingResults.intermediates.placeId",
    )
)
MAX_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 30.0
SUPPORTED_TRAVEL_MODES = ("DRIVE", "TWO_WHEELER")
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InputError(ValueError):
    """A strict input-envelope validation failure."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class NetworkTransportError(RuntimeError):
    """A retryable network failure without an HTTP response."""


class HttpResponse:
    """Small transport response that is easy to replace in tests."""

    def __init__(
        self, status: int, body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> None:
        self.status = status
        self.body = dict(body)
        self.headers = dict(headers)


class Transport(Protocol):
    def send(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout_seconds: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """HTTPS adapter kept behind the stable route-result contract."""

    def send(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout_seconds: float,
    ) -> HttpResponse:
        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        opener = build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return HttpResponse(
                    response.status,
                    _decode_json_object(response.read(), tolerate_invalid=True),
                    dict(response.headers.items()),
                )
        except HTTPError as error:
            return HttpResponse(
                error.code,
                _decode_json_object(error.read(), tolerate_invalid=True),
                dict(error.headers.items()) if error.headers else {},
            )
        except (URLError, TimeoutError, OSError) as error:
            raise NetworkTransportError("Google Routes 網路請求失敗") from error


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep the API key on the fixed Google endpoint instead of following redirects."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


class RateLimiter:
    """Serial, process-local proactive request throttling."""

    def __init__(
        self,
        qpm: int,
        *,
        sleep: Callable[[float], None],
        monotonic: Callable[[], float],
    ) -> None:
        self._interval = 60.0 / qpm
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self._interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now


def capabilities() -> dict[str, object]:
    return {
        "skill_name": "google-routes",
        "skill_version": SKILL_VERSION,
        "cli_contract_version": CLI_CONTRACT_VERSION,
        "schema_versions": list(SUPPORTED_SCHEMA_VERSIONS),
        "commands": [
            "capabilities",
            "credentials path",
            "credentials check",
            "credentials set",
            "query",
        ],
        "travel_modes": list(SUPPORTED_TRAVEL_MODES),
        "output_profiles": ["summary", "itinerary_summary"],
        "itinerary_limits": {
            "minimum_points": 2,
            "maximum_points": 12,
            "maximum_intermediate_waypoints": 10,
            "waypoint_order": "fixed",
            "intermediate_type": "stopover",
            "optimization_supported": False,
        },
        "estimated_sku_by_travel_mode": {
            "DRIVE": "Routes: Compute Routes Pro",
            "TWO_WHEELER": "Routes: Compute Routes Enterprise",
        },
        "default_rate_limit_qpm": 60,
        "rate_limit_qpm_range": {"minimum": 1, "maximum": 3000},
        "max_retries": MAX_RETRIES,
    }


def validate_batch(value: object) -> dict[str, object]:
    payload = _require_object(value, "$")
    _reject_unknown(
        payload,
        {"schema_version", "profile", "rate_limit_qpm", "requests"},
        "$",
    )
    _require_fields(payload, {"schema_version", "profile", "requests"}, "$")
    schema_version = payload["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise InputError(
            "$.schema_version", f"只支援版本 {'、'.join(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    expected_profile = "summary" if schema_version == "1" else "itinerary_summary"
    if payload["profile"] != expected_profile:
        raise InputError("$.profile", f"schema v{schema_version} 必須使用 {expected_profile}")
    qpm = payload.get("rate_limit_qpm", 60)
    if isinstance(qpm, bool) or not isinstance(qpm, int) or not 1 <= qpm <= 3000:
        raise InputError("$.rate_limit_qpm", "必須是 1 到 3000 的整數")
    requests = payload["requests"]
    if not isinstance(requests, list) or not requests:
        raise InputError("$.requests", "必須是至少包含一筆的陣列")

    request_ids: set[str] = set()
    validated_requests: list[dict[str, object]] = []
    for index, item in enumerate(requests):
        path = f"$.requests[{index}]"
        request_item = _require_object(item, path)
        route_fields = (
            {"request_id", "origin", "destination", "travel_mode", "departure_time"}
            if schema_version == "1"
            else {"request_id", "points", "travel_mode", "departure_time"}
        )
        _reject_unknown(request_item, route_fields, path)
        _require_fields(request_item, route_fields, path)
        request_id = _require_nonempty_string(request_item["request_id"], f"{path}.request_id")
        if not REQUEST_ID.fullmatch(request_id):
            raise InputError(
                f"{path}.request_id",
                "必須是 1–128 字元，且只使用英數字、點、底線或連字號",
            )
        if request_id in request_ids:
            raise InputError(f"{path}.request_id", "request_id 不得重複")
        request_ids.add(request_id)
        route_locations: dict[str, object]
        if schema_version == "1":
            route_locations = {
                "origin": _validate_location(request_item["origin"], f"{path}.origin"),
                "destination": _validate_location(
                    request_item["destination"], f"{path}.destination"
                ),
            }
        else:
            points_value = request_item["points"]
            if not isinstance(points_value, list) or not 2 <= len(points_value) <= 12:
                raise InputError(f"{path}.points", "必須包含 2 到 12 個有順序的地點")
            points: list[dict[str, object]] = []
            for point_index, point_value in enumerate(points_value):
                point_path = f"{path}.points[{point_index}]"
                point = _require_object(point_value, point_path)
                _reject_unknown(point, {"label", "location"}, point_path)
                _require_fields(point, {"label", "location"}, point_path)
                label = _require_nonempty_string(point["label"], f"{point_path}.label")
                if len(label) > 80:
                    raise InputError(f"{point_path}.label", "不得超過 80 個字元")
                points.append(
                    {
                        "label": label,
                        "location": _validate_location(
                            point["location"], f"{point_path}.location"
                        ),
                    }
                )
            route_locations = {"points": points}
        travel_mode = request_item["travel_mode"]
        if travel_mode not in SUPPORTED_TRAVEL_MODES:
            raise InputError(
                f"{path}.travel_mode",
                f"必須是 {' 或 '.join(SUPPORTED_TRAVEL_MODES)}",
            )
        departure_time = _validate_departure_time(
            request_item["departure_time"], f"{path}.departure_time"
        )
        validated_requests.append(
            {
                "request_id": request_id,
                **route_locations,
                "travel_mode": travel_mode,
                "departure_time": departure_time,
            }
        )
    return {
        "schema_version": schema_version,
        "profile": expected_profile,
        "rate_limit_qpm": qpm,
        "requests": validated_requests,
    }


def build_provider_request(item: Mapping[str, object]) -> dict[str, object]:
    travel_mode = str(item["travel_mode"])
    if "points" in item:
        points = item["points"]
        assert isinstance(points, list)
        locations = [point["location"] for point in points]
        origin = locations[0]
        destination = locations[-1]
        intermediates = [_provider_location(location) for location in locations[1:-1]]
    else:
        origin = item["origin"]
        destination = item["destination"]
        intermediates = []
    request: dict[str, object] = {
        "origin": _provider_location(origin),
        "destination": _provider_location(destination),
        "travelMode": travel_mode,
        "routingPreference": (
            "TRAFFIC_AWARE_OPTIMAL" if travel_mode == "DRIVE" else "TRAFFIC_AWARE"
        ),
        "departureTime": item["departure_time"],
        "computeAlternativeRoutes": False,
    }
    if intermediates:
        request["intermediates"] = intermediates
    if travel_mode == "DRIVE":
        request["trafficModel"] = "BEST_GUESS"
    return request


def execute_batch(
    payload: object,
    *,
    api_key: str,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    max_retries: int = MAX_RETRIES,
) -> tuple[dict[str, object], int]:
    validated = validate_batch(payload)
    if not api_key:
        raise InputError("$credentials.api_key", "尚未解析有效 credential")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int):
        raise ValueError("max_retries 必須是 0 到 2 的整數")
    if not 0 <= max_retries <= MAX_RETRIES:
        raise ValueError("max_retries 必須是 0 到 2 的整數")
    adapter = transport or UrllibTransport()
    limiter = RateLimiter(
        int(validated["rate_limit_qpm"]), sleep=sleep, monotonic=monotonic
    )
    results = [
        _execute_one(
            item,
            api_key,
            adapter,
            limiter,
            sleep,
            max_retries,
            str(validated["profile"]),
        )
        for item in validated["requests"]
    ]
    statuses = {str(result["status"]) for result in results}
    if statuses == {"success"}:
        batch_status, exit_code = "success", 0
    elif "error" not in statuses:
        batch_status, exit_code = "degraded", 3
    elif statuses == {"error"}:
        batch_status, exit_code = "failure", 4
    else:
        batch_status, exit_code = "partial_success", 3
    return (
        {
            "schema_version": validated["schema_version"],
            "cli_contract_version": CLI_CONTRACT_VERSION,
            "profile": validated["profile"],
            "status": batch_status,
            "results": results,
        },
        exit_code,
    )


def _execute_one(
    item: Mapping[str, object],
    api_key: str,
    transport: Transport,
    limiter: RateLimiter,
    sleep: Callable[[float], None],
    max_retries: int,
    profile: str,
) -> dict[str, object]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            ITINERARY_FIELD_MASK if profile == "itinerary_summary" else FIELD_MASK
        ),
    }
    provider_request = build_provider_request(item)
    attempts = 0
    last_error: dict[str, object] | None = None
    while attempts <= max_retries:
        attempts += 1
        limiter.wait()
        try:
            response = transport.send(
                ROUTES_ENDPOINT, headers, provider_request, DEFAULT_TIMEOUT_SECONDS
            )
        except NetworkTransportError:
            last_error = {
                "code": "network_error",
                "message": "無法連線至 Google Routes API",
                "retryable": True,
            }
            if attempts <= max_retries:
                sleep(float(2 ** (attempts - 1)))
                continue
            break

        if 200 <= response.status < 300:
            try:
                return _normalize_response(item, response.body, attempts)
            except ValueError:
                return _error_result(
                    item,
                    attempts,
                    "invalid_provider_response",
                    "Google Routes API 回應缺少必要欄位或格式錯誤",
                    False,
                )

        retryable = response.status == 429 or 500 <= response.status <= 599
        last_error = _provider_http_error(response, retryable)
        if retryable and attempts <= max_retries:
            delay = _retry_delay(response.headers, attempts)
            sleep(delay)
            continue
        break

    assert last_error is not None
    return _error_result(
        item,
        attempts,
        str(last_error["code"]),
        str(last_error["message"]),
        bool(last_error["retryable"]),
        last_error.get("http_status"),
    )


def _normalize_response(
    item: Mapping[str, object], response: Mapping[str, Any], attempts: int
) -> dict[str, object]:
    routes = response.get("routes")
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
        raise ValueError("missing route")
    route = routes[0]
    distance = route.get("distanceMeters")
    if isinstance(distance, bool) or not isinstance(distance, int) or distance < 0:
        raise ValueError("invalid distance")
    duration = _duration_seconds(route.get("duration"))
    static_duration = _duration_seconds(route.get("staticDuration"))
    warnings = route.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(value, str) for value in warnings):
        raise ValueError("invalid warnings")
    fallback_value = response.get("fallbackInfo")
    fallback: dict[str, str] | None = None
    if fallback_value is not None:
        if not isinstance(fallback_value, dict):
            raise ValueError("invalid fallback")
        routing_mode = fallback_value.get("routingMode")
        reason = fallback_value.get("reason")
        if not isinstance(routing_mode, str) or not isinstance(reason, str):
            raise ValueError("invalid fallback fields")
        fallback = {"routing_mode": routing_mode, "reason": reason}

    geocoding = response.get("geocodingResults", {})
    if not isinstance(geocoding, dict):
        raise ValueError("invalid geocoding results")
    if "points" in item:
        return _normalize_itinerary_result(
            item=item,
            route=route,
            geocoding=geocoding,
            attempts=attempts,
            distance=distance,
            duration=duration,
            static_duration=static_duration,
            warnings=warnings,
            fallback=fallback,
        )
    origin_place_id = _resolved_place_id(item["origin"], geocoding.get("origin"))
    destination_place_id = _resolved_place_id(
        item["destination"], geocoding.get("destination")
    )
    return {
        "request_id": item["request_id"],
        "status": "degraded" if fallback else "success",
        "travel_mode": item["travel_mode"],
        "distance_meters": distance,
        "duration_seconds": duration,
        "static_duration_seconds": static_duration,
        "warnings": warnings,
        "fallback": fallback,
        "origin_place_id": origin_place_id,
        "destination_place_id": destination_place_id,
        "attempts": attempts,
    }


def _normalize_itinerary_result(
    *,
    item: Mapping[str, object],
    route: Mapping[str, Any],
    geocoding: Mapping[str, Any],
    attempts: int,
    distance: int,
    duration: int | float,
    static_duration: int | float,
    warnings: list[str],
    fallback: dict[str, str] | None,
) -> dict[str, object]:
    raw_points = item["points"]
    assert isinstance(raw_points, list)
    raw_legs = route.get("legs")
    if not isinstance(raw_legs, list) or len(raw_legs) != len(raw_points) - 1:
        raise ValueError("invalid itinerary legs")

    intermediate_place_ids: dict[int, str] = {}
    raw_intermediates = geocoding.get("intermediates", [])
    if not isinstance(raw_intermediates, list):
        raise ValueError("invalid intermediate geocoding results")
    for value in raw_intermediates:
        if not isinstance(value, dict):
            raise ValueError("invalid intermediate geocoding result")
        index = value.get("intermediateWaypointRequestIndex")
        place_id = value.get("placeId")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(raw_points) - 2
            or not isinstance(place_id, str)
        ):
            raise ValueError("invalid intermediate geocoding fields")
        intermediate_place_ids[index] = place_id

    normalized_points: list[dict[str, object]] = []
    for index, raw_point in enumerate(raw_points):
        assert isinstance(raw_point, dict)
        location = raw_point["location"]
        if index == 0:
            place_id = _resolved_place_id(location, geocoding.get("origin"))
        elif index == len(raw_points) - 1:
            place_id = _resolved_place_id(location, geocoding.get("destination"))
        else:
            place_id = _resolved_place_id(location, None) or intermediate_place_ids.get(
                index - 1
            )
        normalized_points.append(
            {"label": raw_point["label"], "place_id": place_id}
        )

    normalized_legs: list[dict[str, object]] = []
    for index, raw_leg in enumerate(raw_legs):
        if not isinstance(raw_leg, dict):
            raise ValueError("invalid itinerary leg")
        leg_distance = raw_leg.get("distanceMeters")
        if (
            isinstance(leg_distance, bool)
            or not isinstance(leg_distance, int)
            or leg_distance < 0
        ):
            raise ValueError("invalid itinerary leg distance")
        normalized_legs.append(
            {
                "from_label": normalized_points[index]["label"],
                "to_label": normalized_points[index + 1]["label"],
                "distance_meters": leg_distance,
                "duration_seconds": _duration_seconds(raw_leg.get("duration")),
                "static_duration_seconds": _duration_seconds(
                    raw_leg.get("staticDuration")
                ),
            }
        )

    return {
        "request_id": item["request_id"],
        "status": "degraded" if fallback else "success",
        "travel_mode": item["travel_mode"],
        "distance_meters": distance,
        "duration_seconds": duration,
        "static_duration_seconds": static_duration,
        "warnings": warnings,
        "fallback": fallback,
        "points": normalized_points,
        "legs": normalized_legs,
        "attempts": attempts,
    }


def _provider_http_error(
    response: HttpResponse, retryable: bool
) -> dict[str, object]:
    provider_error = response.body.get("error", {})
    status_name = provider_error.get("status") if isinstance(provider_error, dict) else None
    code = status_name if isinstance(status_name, str) else f"http_{response.status}"
    return {
        "code": code,
        "message": f"Google Routes API 回傳 HTTP {response.status}",
        "retryable": retryable,
        "http_status": response.status,
    }


def _error_result(
    item: Mapping[str, object],
    attempts: int,
    code: str,
    message: str,
    retryable: bool,
    http_status: object = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if isinstance(http_status, int):
        error["http_status"] = http_status
    return {
        "request_id": item["request_id"],
        "status": "error",
        "travel_mode": item["travel_mode"],
        "error": error,
        "attempts": attempts,
    }


def _retry_delay(headers: Mapping[str, str], attempts: int) -> float:
    retry_after = next(
        (value for key, value in headers.items() if key.lower() == "retry-after"), None
    )
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return float(2 ** (attempts - 1))


def _validate_location(value: object, path: str) -> dict[str, str]:
    location = _require_object(value, path)
    if set(location) not in ({"address"}, {"place_id"}):
        raise InputError(path, "必須且只能提供 address 或 place_id")
    key = next(iter(location))
    return {key: _require_nonempty_string(location[key], f"{path}.{key}")}


def _validate_departure_time(value: object, path: str) -> str:
    text = _require_nonempty_string(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise InputError(path, "必須是 RFC 3339 日期時間") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(path, "必須包含明確 UTC offset 或 Z")
    if parsed <= datetime.now(timezone.utc):
        raise InputError(path, "必須是未來時間")
    return text


def _provider_location(value: object) -> dict[str, str]:
    assert isinstance(value, dict)
    if "address" in value:
        return {"address": str(value["address"])}
    return {"placeId": str(value["place_id"])}


def _resolved_place_id(request_location: object, geocoded: object) -> str | None:
    assert isinstance(request_location, dict)
    if "place_id" in request_location:
        return str(request_location["place_id"])
    if isinstance(geocoded, dict) and isinstance(geocoded.get("placeId"), str):
        return geocoded["placeId"]
    return None


def _duration_seconds(value: object) -> int | float:
    if not isinstance(value, str) or not value.endswith("s"):
        raise ValueError("invalid duration")
    seconds = float(value[:-1])
    if seconds < 0:
        raise ValueError("negative duration")
    return int(seconds) if seconds.is_integer() else seconds


def _decode_json_object(raw: bytes, *, tolerate_invalid: bool = False) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if tolerate_invalid:
            return {}
        raise ValueError("provider response is not JSON") from None
    if not isinstance(decoded, dict):
        if tolerate_invalid:
            return {}
        raise ValueError("provider response is not an object")
    return decoded


def _require_object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(path, "必須是 JSON object")
    return value


def _require_nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(path, "必須是非空字串")
    return value


def _reject_unknown(value: Mapping[str, object], allowed: set[str], path: str) -> None:
    for key in value:
        if key not in allowed:
            raise InputError(f"{path}.{key}", "未知欄位")


def _require_fields(value: Mapping[str, object], required: set[str], path: str) -> None:
    for key in sorted(required):
        if key not in value:
            raise InputError(f"{path}.{key}", "缺少必要欄位")


def _write_json(stream: TextIO, value: object) -> None:
    json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
    stream.write("\n")


def run(
    argv: list[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    environ: Mapping[str, str] = os.environ,
    transport: Transport | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
    credential_path: Path | None = None,
    credential_reader: Callable[[str], str] | None = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["capabilities"]:
        _write_json(stdout, capabilities())
        return 0
    resolved_credential_path = credential_path or google_routes_credentials.default_credentials_path(
        platform_name=sys.platform if platform_name is None else platform_name,
        environ=environ,
        home=Path.home() if home is None else home,
    )
    if arguments == ["credentials", "path"]:
        _write_json(
            stdout,
            {
                "schema_version": SCHEMA_VERSION,
                "credential": {"path": str(resolved_credential_path)},
            },
        )
        return 0
    if arguments == ["credentials", "set"]:
        try:
            if credential_reader is None:
                if not stdin.isatty():
                    raise google_routes_credentials.CredentialError(
                        "credential_interactive_required",
                        "$credential_file.api_key",
                        "credentials set 必須在互動式終端執行",
                    )
                stored = google_routes_credentials.write_credentials(
                    path=resolved_credential_path
                )
            else:
                stored = google_routes_credentials.write_credentials(
                    path=resolved_credential_path,
                    api_key_reader=credential_reader,
                )
        except google_routes_credentials.CredentialError as error:
            return _write_credential_error(error, stdout, stderr)
        _write_json(
            stdout,
            {
                "schema_version": SCHEMA_VERSION,
                "credential": {
                    "configured": True,
                    "schema_version": stored.schema_version,
                    "path": str(stored.path),
                    "warnings": _credential_warnings(
                        sys.platform if platform_name is None else platform_name
                    ),
                },
            },
        )
        print("google-routes secret file 已安全更新。", file=stderr)
        return 0
    if arguments == ["credentials", "check"]:
        try:
            stored = google_routes_credentials.load_credentials(
                path=resolved_credential_path,
                environ=environ,
                reject_legacy_environment=False,
            )
            if google_routes_credentials.legacy_environment_variable_is_set(environ):
                raise google_routes_credentials.CredentialError(
                    "legacy_api_key_environment_variable",
                    "$environment.GOOGLE_MAPS_API_KEY",
                    "secret file 有效，但仍須移除舊環境變數",
                )
        except google_routes_credentials.CredentialError as error:
            return _write_credential_error(error, stdout, stderr)
        _write_json(
            stdout,
            {
                "schema_version": SCHEMA_VERSION,
                "credential": {
                    "configured": True,
                    "schema_version": stored.schema_version,
                    "path": str(stored.path),
                    "warnings": _credential_warnings(
                        sys.platform if platform_name is None else platform_name
                    ),
                },
            },
        )
        return 0
    if arguments != ["query"]:
        _write_json(
            stdout,
            {
                "schema_version": SCHEMA_VERSION,
                "error": {
                    "code": "usage_error",
                    "message": (
                        "用法：google_routes.py capabilities | credentials "
                        "path|check|set | query"
                    ),
                },
            },
        )
        print("請指定 capabilities、credentials path|check|set 或 query。", file=stderr)
        return 2
    try:
        payload = json.load(stdin)
    except json.JSONDecodeError as error:
        input_error = InputError("$", f"無效 JSON（第 {error.lineno} 行第 {error.colno} 欄）")
        return _write_input_error(input_error, stdout, stderr)
    try:
        validated = validate_batch(payload)
        stored = google_routes_credentials.load_credentials(
            path=resolved_credential_path,
            environ=environ,
        )
        result, exit_code = execute_batch(
            validated, api_key=stored.api_key, transport=transport
        )
    except google_routes_credentials.CredentialError as error:
        return _write_credential_error(error, stdout, stderr)
    except InputError as error:
        return _write_input_error(error, stdout, stderr)
    _write_json(stdout, result)
    counts = {
        status: sum(1 for item in result["results"] if item["status"] == status)
        for status in ("success", "degraded", "error")
    }
    print(
        "路線批次完成："
        f"成功 {counts['success']}、降級 {counts['degraded']}、失敗 {counts['error']}。",
        file=stderr,
    )
    return exit_code


def _credential_warnings(platform_name: str) -> list[dict[str, str]]:
    if platform_name != "win32":
        return []
    return [
        {
            "code": "windows_acl_not_verified",
            "message": (
                "檔案繼承 user-profile ACL；請以 icacls 檢查未授權帳號無讀取權限"
            ),
        }
    ]


def _write_credential_error(
    error: google_routes_credentials.CredentialError,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    _write_json(
        stdout,
        {
            "schema_version": SCHEMA_VERSION,
            "error": {
                "code": error.code,
                "path": error.path,
                "message": error.message,
            },
        },
    )
    print(f"Credential 錯誤：{error.code}（{error.path}）。", file=stderr)
    return 2


def _write_input_error(error: InputError, stdout: TextIO, stderr: TextIO) -> int:
    _write_json(
        stdout,
        {
            "schema_version": SCHEMA_VERSION,
            "error": {
                "code": "invalid_input",
                "path": error.path,
                "message": error.message,
            },
        },
    )
    print(f"輸入錯誤：{error.path}。", file=stderr)
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
