from __future__ import annotations

import copy
import json
import hashlib
import os
import re
import subprocess
import sys
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, TextIO


SKILL_VERSION = "2.0.0"
CLI_CONTRACT_VERSION = "2.0.0"
INSTALL_COMMAND = "npx skills add Command1264/agent-skills"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
UTC_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
LOCAL_TIME = re.compile(r"^(\d{2}):(\d{2})$")


class InputError(ValueError):
    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


def discover_google_routes(
    *,
    environ: Mapping[str, str],
    commute_skill_dir: Path,
    cwd: Path,
    home: Path,
) -> Path:
    candidates: list[Path] = []
    override = environ.get("GOOGLE_ROUTES_SKILL_DIR")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend(
        [
            commute_skill_dir.parent / "google-routes",
            cwd / ".agents" / "skills" / "google-routes",
            home / ".agents" / "skills" / "google-routes",
        ]
    )
    for candidate in candidates:
        if (
            (candidate / "SKILL.md").is_file()
            and (candidate / "scripts" / "google_routes.py").is_file()
        ):
            return candidate.resolve()
    raise InputError(
        "GOOGLE_ROUTES_NOT_FOUND",
        "找不到可執行的 google-routes Skill。請先執行：" + INSTALL_COMMAND,
    )


def validate_google_routes_capabilities(
    value: object, dependency_path: Path
) -> dict[str, object]:
    problems: list[str] = []
    if not isinstance(value, dict):
        problems.append("capabilities 不是 JSON object")
        capabilities_value: dict[str, object] = {}
    else:
        capabilities_value = value

    skill_version = capabilities_value.get("skill_version")
    major = None
    if isinstance(skill_version, str):
        first = skill_version.split(".", 1)[0]
        if first.isdigit():
            major = int(first)
    if capabilities_value.get("skill_name") != "google-routes":
        problems.append("skill_name 必須是 google-routes")
    if major != 2:
        problems.append("skill_version major 必須是 2")
    if capabilities_value.get("cli_contract_version") != "2.0.0":
        problems.append("cli_contract_version 必須是 2.0.0")
    if "2" not in _string_list(capabilities_value.get("schema_versions")):
        problems.append("必須支援 schema version 2")
    modes = set(_string_list(capabilities_value.get("travel_modes")))
    if not {"DRIVE", "TWO_WHEELER"}.issubset(modes):
        problems.append("必須支援 DRIVE 與 TWO_WHEELER")
    if "itinerary_summary" not in _string_list(
        capabilities_value.get("output_profiles")
    ):
        problems.append("必須支援 itinerary_summary profile")
    limits_value = capabilities_value.get("itinerary_limits")
    limits = limits_value if isinstance(limits_value, dict) else {}
    required_limits = {
        "minimum_points": 2,
        "maximum_points": 12,
        "maximum_intermediate_waypoints": 10,
        "waypoint_order": "fixed",
    }
    for key, expected in required_limits.items():
        if limits.get(key) != expected:
            problems.append(f"itinerary_limits.{key} 必須是 {expected}")
    if limits.get("intermediate_type") != "stopover":
        problems.append("itinerary_limits.intermediate_type 必須是 stopover")
    if limits.get("optimization_supported") is not False:
        problems.append("itinerary_limits.optimization_supported 必須是 false")
    if problems:
        raise InputError(
            "GOOGLE_ROUTES_INCOMPATIBLE",
            "已找到 google-routes，但能力不相容："
            + "；".join(problems)
            + "。請更新 google-routes："
            + INSTALL_COMMAND,
        )
    return {
        "path": str(dependency_path.resolve()),
        "skill_version": skill_version,
        "cli_contract_version": "2.0.0",
        "schema_version": "2",
        "travel_modes": ["DRIVE", "TWO_WHEELER"],
        "output_profile": "itinerary_summary",
        "itinerary_limits": required_limits,
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def build_plan(
    request_value: object,
    config_value: object,
    dependency_value: Mapping[str, object],
    *,
    now: datetime,
) -> dict[str, object]:
    normalized = _normalize_planning_inputs(request_value, config_value)
    offset = _parse_utc_offset(normalized["utc_offset"], "$config.utc_offset")
    local_now = now.astimezone(offset)
    start = _plan_start_date(normalized.get("start_date"), local_now.date())
    weeks = _bounded_int(normalized["weeks"], "$.weeks", 1, 4)
    weekdays = _weekdays(normalized["weekdays"])
    outbound_time = _local_time(
        normalized["outbound_departure_time"],
        "$.outbound_departure_time",
    )
    return_time = _local_time(
        normalized["return_departure_time"],
        "$.return_departure_time",
    )
    modes = _travel_modes(normalized["travel_modes"], "$.travel_modes")
    rate_limit_qpm = _bounded_int(
        normalized["rate_limit_qpm"], "$.rate_limit_qpm", 1, 3000
    )
    confirmation_threshold = _bounded_int(
        normalized["confirmation_threshold"],
        "$.confirmation_threshold",
        1,
        1000,
    )

    selected_dates = [
        start + timedelta(days=day_index)
        for day_index in range(weeks * 7)
        if (start + timedelta(days=day_index)).isoweekday() in weekdays
    ]
    if not selected_dates:
        raise InputError("INVALID_INPUT", "沒有符合 weekdays 的取樣日期", "$.weekdays")

    samples: list[dict[str, object]] = []
    journeys = normalized["journeys"]
    assert isinstance(journeys, list)
    for sample_date in selected_dates:
        for journey in journeys:
            assert isinstance(journey, dict)
            for direction, departure_clock in (
                ("outbound", outbound_time),
                ("return", return_time),
            ):
                points = journey[direction]
                assert isinstance(points, list)
                departure = datetime.combine(sample_date, departure_clock, tzinfo=offset)
                if departure <= now.astimezone(offset):
                    raise InputError(
                        "DEPARTURE_NOT_FUTURE",
                        "所有 departure_time 都必須晚於目前時間",
                        "$.start_date",
                    )
                for mode in modes:
                    request_id = ".".join(
                        [
                            str(journey["id"]),
                            sample_date.strftime("%Y%m%d"),
                            direction,
                            mode.lower().replace("_", "-"),
                        ]
                    )
                    samples.append(
                        {
                            "request_id": request_id,
                            "journey_id": journey["id"],
                            "journey_label": journey["label"],
                            "date": sample_date.isoformat(),
                            "direction": direction,
                            "points": points,
                            "travel_mode": mode,
                            "departure_time": departure.isoformat(),
                            "expected_leg_count": len(points) - 1,
                        }
                    )

    request_count = len(samples)
    enterprise = sum(
        1 for sample in samples if sample["travel_mode"] == "TWO_WHEELER"
    )
    pro = request_count - enterprise
    journey_previews = []
    for journey in journeys:
        assert isinstance(journey, dict)
        directions = []
        for direction in ("outbound", "return"):
            points = journey[direction]
            assert isinstance(points, list)
            directions.append(
                {
                    "direction": direction,
                    "point_labels": [point["label"] for point in points],
                    "point_count": len(points),
                    "intermediate_count": len(points) - 2,
                    "leg_count": len(points) - 1,
                }
            )
        journey_previews.append(
            {
                "journey_id": journey["id"],
                "journey_label": journey["label"],
                "directions": directions,
            }
        )
    plan_without_id: dict[str, object] = {
        "schema_version": "2",
        "plan_contract_version": "2.0.0",
        "created_at": now.isoformat(),
        "input_compatibility": {
            "config_schema_version": normalized["config_schema_version"],
            "plan_request_schema_version": normalized[
                "plan_request_schema_version"
            ],
            "adapter": normalized["adapter"],
        },
        "dependency": copy.deepcopy(dict(dependency_value)),
        "schedule": {
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=weeks * 7 - 1)).isoformat(),
            "weeks": weeks,
            "weekdays": weekdays,
            "dates": [item.isoformat() for item in selected_dates],
            "utc_offset": normalized["utc_offset"],
            "outbound_departure_time": outbound_time.strftime("%H:%M"),
            "return_departure_time": return_time.strftime("%H:%M"),
            "travel_modes": modes,
        },
        "preview": {
            "journey_count": len(journeys),
            "request_count": request_count,
            "planned_leg_count": sum(
                int(sample["expected_leg_count"]) for sample in samples
            ),
            "retry_limit": 2,
            "maximum_http_requests": request_count * 3,
            "rate_limit_qpm": rate_limit_qpm,
            "local_rate_limit_only": True,
            "confirmation_threshold": confirmation_threshold,
            "confirmation_required": request_count > confirmation_threshold,
            "estimated_sku_requests": {
                "routes_compute_pro": pro,
                "routes_compute_enterprise": enterprise,
            },
            "journeys": journey_previews,
        },
        "samples": samples,
    }
    return {
        **plan_without_id,
        "plan_id": _content_id(plan_without_id),
    }


def _normalize_planning_inputs(
    request_value: object, config_value: object
) -> dict[str, object]:
    request = _require_object(request_value, "$")
    config = _require_object(config_value, "$config")
    request_version = request.get("schema_version")
    config_version = config.get("schema_version")
    if request_version != config_version:
        raise InputError(
            "INCOMPATIBLE_INPUT_SCHEMA_VERSIONS",
            "config 與 plan request 必須同為 schema version 1 或 2",
            "$.schema_version",
        )
    if request_version == "1":
        return _normalize_v1_inputs(request, config)
    if request_version == "2":
        return _normalize_v2_inputs(request, config)
    raise InputError(
        "INVALID_INPUT",
        "schema_version 必須是 1 或 2",
        "$.schema_version",
    )


def _normalize_v1_inputs(
    request: Mapping[str, object], config_value: Mapping[str, object]
) -> dict[str, object]:
    _reject_unknown(
        request,
        {
            "schema_version",
            "start_date",
            "weeks",
            "weekdays",
            "morning_departure_time",
            "evening_departure_time",
            "travel_modes",
            "rate_limit_qpm",
            "confirmation_threshold",
            "additional_companies",
            "schedule_mode",
        },
        "$",
    )
    if request.get("schedule_mode", "fixed_departure") != "fixed_departure":
        raise InputError(
            "UNSUPPORTED_SCHEDULE_MODE",
            "v1 只支援 fixed_departure；target_arrival 尚未支援",
            "$.schedule_mode",
        )
    config = _validate_config(config_value)
    home = config["home"]
    assert isinstance(home, dict)
    home_label = _label(
        home["label"], "$config.home.label", "LEGACY_POINT_LABEL_INCOMPATIBLE"
    )
    companies = list(config["companies"])
    company_paths = [
        f"$config.companies[{index}]" for index in range(len(companies))
    ]
    additional = request.get("additional_companies", [])
    if not isinstance(additional, list):
        raise InputError("INVALID_INPUT", "必須是 array", "$.additional_companies")
    for index, company_value in enumerate(additional):
        path = f"$.additional_companies[{index}]"
        companies.append(_validate_company(company_value, path))
        company_paths.append(path)
    seen_company_ids: set[str] = set()
    journeys: list[dict[str, object]] = []
    for company, path in zip(companies, company_paths):
        assert isinstance(company, dict)
        company_id = str(company["id"])
        if company_id in seen_company_ids:
            raise InputError(
                "INVALID_INPUT", "company id 不得重複", f"{path}.id"
            )
        seen_company_ids.add(company_id)
        company_label = _label(
            company["name"],
            f"{path}.name",
            "LEGACY_POINT_LABEL_INCOMPATIBLE",
        )
        if company_label == home_label:
            raise InputError(
                "DUPLICATE_POINT_LABEL",
                "同一 direction 的 Point label 不得重複",
                f"{path}.name",
            )
        outbound = [
            {"label": home_label, "location": dict(home["location"])},
            {"label": company_label, "location": dict(company["location"])},
        ]
        journeys.append(
            {
                "id": company_id,
                "label": company_label,
                "outbound": outbound,
                "return": [
                    {"label": point["label"], "location": dict(point["location"])}
                    for point in reversed(outbound)
                ],
            }
        )
    return {
        "config_schema_version": "1",
        "plan_request_schema_version": "1",
        "adapter": "v1_to_v2",
        "start_date": request.get("start_date"),
        "weeks": request.get("weeks", 1),
        "weekdays": request.get("weekdays", [1, 2, 3, 4, 5]),
        "outbound_departure_time": request.get(
            "morning_departure_time", config["morning_departure_time"]
        ),
        "return_departure_time": request.get(
            "evening_departure_time", config["evening_departure_time"]
        ),
        "travel_modes": request.get("travel_modes", ["TWO_WHEELER", "DRIVE"]),
        "rate_limit_qpm": request.get("rate_limit_qpm", 60),
        "confirmation_threshold": request.get("confirmation_threshold", 20),
        "utc_offset": config["utc_offset"],
        "journeys": journeys,
    }


def _normalize_v2_inputs(
    request: Mapping[str, object], config: Mapping[str, object]
) -> dict[str, object]:
    validated_config = _validate_v2_config(config)
    locations = validated_config["location_catalog"]
    assert isinstance(locations, dict)
    utc_offset = str(validated_config["utc_offset"])
    config_outbound_time = str(validated_config["outbound_departure_time"])
    config_return_time = str(validated_config["return_departure_time"])

    _reject_unknown(
        request,
        {
            "schema_version",
            "start_date",
            "weeks",
            "weekdays",
            "outbound_departure_time",
            "return_departure_time",
            "travel_modes",
            "rate_limit_qpm",
            "confirmation_threshold",
            "schedule_mode",
            "journeys",
        },
        "$",
    )
    _require_fields(request, {"schema_version", "journeys"}, "$", "INVALID_INPUT")
    if request.get("schedule_mode", "fixed_departure") != "fixed_departure":
        raise InputError(
            "UNSUPPORTED_SCHEDULE_MODE",
            "v2 只支援 fixed_departure；target_arrival 尚未支援",
            "$.schedule_mode",
        )
    journeys_value = request["journeys"]
    if not isinstance(journeys_value, list) or not journeys_value:
        raise InputError("INVALID_INPUT", "journeys 必須是非空 array", "$.journeys")
    journeys: list[dict[str, object]] = []
    journey_ids: set[str] = set()
    for index, item in enumerate(journeys_value):
        path = f"$.journeys[{index}]"
        journey = _require_object(item, path)
        _reject_unknown(journey, {"id", "label", "outbound", "return"}, path)
        _require_fields(
            journey,
            {"id", "label", "outbound", "return"},
            path,
            "INVALID_INPUT",
        )
        journey_id = _safe_id(journey["id"], f"{path}.id", "INVALID_INPUT")
        if journey_id in journey_ids:
            raise InputError(
                "DUPLICATE_JOURNEY_ID",
                "Commute Journey id 不得重複",
                f"{path}.id",
            )
        journey_ids.add(journey_id)
        outbound = _resolve_direction(
            journey["outbound"], f"{path}.outbound", locations
        )
        return_value = _require_object(journey["return"], f"{path}.return")
        if set(return_value) == {"reverse_outbound"}:
            if return_value["reverse_outbound"] is not True:
                raise InputError(
                    "INVALID_RETURN_DEFINITION",
                    "reverse_outbound 必須是 true",
                    f"{path}.return.reverse_outbound",
                )
            return_points = [
                {"label": point["label"], "location": dict(point["location"])}
                for point in reversed(outbound)
            ]
        elif set(return_value) == {"points"}:
            return_points = _resolve_points(
                return_value["points"], f"{path}.return.points", locations
            )
        else:
            raise InputError(
                "INVALID_RETURN_DEFINITION",
                "return 必須且只能提供 points 或 reverse_outbound: true",
                f"{path}.return",
            )
        journeys.append(
            {
                "id": journey_id,
                "label": _label(journey["label"], f"{path}.label", "INVALID_INPUT"),
                "outbound": outbound,
                "return": return_points,
            }
        )
    return {
        "config_schema_version": "2",
        "plan_request_schema_version": "2",
        "adapter": None,
        "start_date": request.get("start_date"),
        "weeks": request.get("weeks", 1),
        "weekdays": request.get("weekdays", [1, 2, 3, 4, 5]),
        "outbound_departure_time": request.get(
            "outbound_departure_time", config_outbound_time
        ),
        "return_departure_time": request.get(
            "return_departure_time", config_return_time
        ),
        "travel_modes": request.get("travel_modes", ["TWO_WHEELER", "DRIVE"]),
        "rate_limit_qpm": request.get("rate_limit_qpm", 60),
        "confirmation_threshold": request.get("confirmation_threshold", 20),
        "utc_offset": utc_offset,
        "journeys": journeys,
    }


def _validate_v2_config(config: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown(
        config,
        {
            "schema_version",
            "locations",
            "utc_offset",
            "outbound_departure_time",
            "return_departure_time",
        },
        "$config",
    )
    _require_fields(
        config,
        {
            "schema_version",
            "locations",
            "utc_offset",
            "outbound_departure_time",
            "return_departure_time",
        },
        "$config",
        "INVALID_CONFIG",
    )
    if config["schema_version"] != "2":
        raise InputError(
            "INVALID_CONFIG", "schema_version 必須是 2", "$config.schema_version"
        )
    locations_value = config["locations"]
    if not isinstance(locations_value, list):
        raise InputError("INVALID_CONFIG", "必須是 array", "$config.locations")
    locations: dict[str, dict[str, object]] = {}
    for index, item in enumerate(locations_value):
        path = f"$config.locations[{index}]"
        location_item = _require_object(item, path)
        _reject_unknown(location_item, {"id", "label", "location"}, path)
        _require_fields(
            location_item,
            {"id", "label", "location"},
            path,
            "INVALID_CONFIG",
        )
        location_id = _safe_id(location_item["id"], f"{path}.id", "INVALID_CONFIG")
        if location_id in locations:
            raise InputError(
                "DUPLICATE_LOCATION_ID",
                "Named Location id 不得重複",
                f"{path}.id",
            )
        locations[location_id] = {
            "label": _label(location_item["label"], f"{path}.label", "INVALID_CONFIG"),
            "location": _validate_location(
                location_item["location"], f"{path}.location"
            ),
        }
    utc_offset = _nonempty_string(config["utc_offset"], "$config.utc_offset")
    _parse_utc_offset(utc_offset, "$config.utc_offset")
    config_outbound_time = _nonempty_string(
        config["outbound_departure_time"], "$config.outbound_departure_time"
    )
    config_return_time = _nonempty_string(
        config["return_departure_time"], "$config.return_departure_time"
    )
    _local_time(config_outbound_time, "$config.outbound_departure_time")
    _local_time(config_return_time, "$config.return_departure_time")
    return {
        "schema_version": "2",
        "utc_offset": utc_offset,
        "outbound_departure_time": config_outbound_time,
        "return_departure_time": config_return_time,
        "location_catalog": locations,
    }


def _resolve_direction(
    value: object, path: str, locations: Mapping[str, dict[str, object]]
) -> list[dict[str, object]]:
    direction = _require_object(value, path)
    _reject_unknown(direction, {"points"}, path)
    _require_fields(direction, {"points"}, path, "INVALID_INPUT")
    return _resolve_points(direction["points"], f"{path}.points", locations)


def _resolve_points(
    value: object, path: str, locations: Mapping[str, dict[str, object]]
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 12:
        raise InputError("INVALID_INPUT", "points 必須包含 2 到 12 個項目", path)
    points: list[dict[str, object]] = []
    labels: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        point = _require_object(item, item_path)
        if set(point) == {"location_id"}:
            location_id = _safe_id(
                point["location_id"], f"{item_path}.location_id", "INVALID_INPUT"
            )
            if location_id not in locations:
                raise InputError(
                    "UNKNOWN_LOCATION_ID",
                    "找不到 Named Location id",
                    f"{item_path}.location_id",
                )
            source = locations[location_id]
            resolved = {
                "label": source["label"],
                "location": dict(source["location"]),
            }
        elif set(point) == {"label", "location"}:
            resolved = {
                "label": _label(point["label"], f"{item_path}.label", "INVALID_INPUT"),
                "location": _validate_location(
                    point["location"], f"{item_path}.location"
                ),
            }
        else:
            raise InputError(
                "INVALID_INPUT",
                "Point 必須且只能使用 location_id，或 label 與 location",
                item_path,
            )
        label = str(resolved["label"])
        if label in labels:
            raise InputError(
                "DUPLICATE_POINT_LABEL",
                "同一 direction 的 Point label 不得重複",
                f"{item_path}.label",
            )
        labels.add(label)
        points.append(resolved)
    return points


def _require_fields(
    value: Mapping[str, object],
    required: set[str],
    path: str,
    code: str,
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise InputError(code, "缺少必要欄位", f"{path}.{missing[0]}")


def _safe_id(value: object, path: str, code: str) -> str:
    text = _nonempty_string(value, path)
    if not SAFE_ID.fullmatch(text):
        raise InputError(code, "id 必須是安全識別符", path)
    return text


def _label(value: object, path: str, code: str) -> str:
    text = _nonempty_string(value, path)
    if len(text) > 80:
        raise InputError(code, "label 最多 80 個字元", path)
    return text


def validate_execution_plan(value: object, *, now: datetime) -> dict[str, object]:
    plan = _require_object(value, "$")
    if plan.get("schema_version") == "1":
        raise InputError(
            "LEGACY_PLAN_REQUIRES_REGENERATION",
            "commute-analyzer v2 不執行 plan v1；請以原始 config 與 request 重新執行 plan",
            "$.schema_version",
        )
    return _validate_execution_plan_v2(plan, now=now)


def _validate_execution_plan_v2(
    plan: Mapping[str, object], *, now: datetime
) -> dict[str, object]:
    _reject_unknown(
        plan,
        {
            "schema_version",
            "plan_contract_version",
            "created_at",
            "input_compatibility",
            "dependency",
            "schedule",
            "preview",
            "samples",
            "plan_id",
        },
        "$",
    )
    _require_fields(
        plan,
        {
            "schema_version",
            "plan_contract_version",
            "created_at",
            "input_compatibility",
            "dependency",
            "schedule",
            "preview",
            "samples",
            "plan_id",
        },
        "$",
        "INVALID_PLAN",
    )
    if plan["schema_version"] != "2":
        raise InputError("INVALID_PLAN", "schema_version 必須是 2", "$.schema_version")
    if plan["plan_contract_version"] != "2.0.0":
        raise InputError(
            "INVALID_PLAN",
            "plan_contract_version 必須是 2.0.0",
            "$.plan_contract_version",
        )
    created_at = _nonempty_string(plan["created_at"], "$.created_at")
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise InputError(
            "INVALID_PLAN", "created_at 必須是 ISO 8601 date-time", "$.created_at"
        ) from exc
    if created.tzinfo is None or created.utcoffset() is None:
        raise InputError(
            "INVALID_PLAN", "created_at 必須包含 UTC offset", "$.created_at"
        )
    plan_id = _nonempty_string(plan["plan_id"], "$.plan_id")
    content = {key: item for key, item in plan.items() if key != "plan_id"}
    if plan_id != _content_id(content):
        raise InputError(
            "PLAN_ID_MISMATCH",
            "plan 內容已改變；請重新執行 plan，並使用新的 plan_id",
            "$.plan_id",
        )
    _validate_input_compatibility(plan["input_compatibility"])
    _validate_plan_dependency(plan["dependency"])

    samples = plan["samples"]
    if not isinstance(samples, list) or not samples:
        raise InputError("INVALID_PLAN", "samples 必須是非空 array", "$.samples")
    request_ids: set[str] = set()
    mode_counts = {"DRIVE": 0, "TWO_WHEELER": 0}
    journey_definitions: dict[str, dict[str, object]] = {}
    sample_dates: set[str] = set()
    planned_leg_count = 0
    for index, sample_value in enumerate(samples):
        path = f"$.samples[{index}]"
        sample = _require_object(sample_value, path)
        _reject_unknown(
            sample,
            {
                "request_id",
                "journey_id",
                "journey_label",
                "date",
                "direction",
                "points",
                "travel_mode",
                "departure_time",
                "expected_leg_count",
            },
            path,
        )
        _require_fields(
            sample,
            {
                "request_id",
                "journey_id",
                "journey_label",
                "date",
                "direction",
                "points",
                "travel_mode",
                "departure_time",
                "expected_leg_count",
            },
            path,
            "INVALID_PLAN",
        )
        request_id = _nonempty_string(sample["request_id"], f"{path}.request_id")
        if not SAFE_REQUEST_ID.fullmatch(request_id):
            raise InputError(
                "INVALID_PLAN", "request_id 必須是安全識別符", f"{path}.request_id"
            )
        if request_id in request_ids:
            raise InputError(
                "INVALID_PLAN", "request_id 不得重複", f"{path}.request_id"
            )
        request_ids.add(request_id)
        journey_id = _safe_id(sample["journey_id"], f"{path}.journey_id", "INVALID_PLAN")
        journey_label = _label(
            sample["journey_label"], f"{path}.journey_label", "INVALID_PLAN"
        )
        direction = sample["direction"]
        if direction not in {"outbound", "return"}:
            raise InputError(
                "INVALID_PLAN",
                "direction 必須是 outbound 或 return",
                f"{path}.direction",
            )
        points = _validate_resolved_points(sample["points"], f"{path}.points")
        expected_leg_count = sample["expected_leg_count"]
        if expected_leg_count != len(points) - 1:
            raise InputError(
                "INVALID_PLAN",
                "expected_leg_count 必須等於 points 數量減一",
                f"{path}.expected_leg_count",
            )
        planned_leg_count += int(expected_leg_count)
        mode = sample["travel_mode"]
        if mode not in mode_counts:
            raise InputError(
                "INVALID_PLAN",
                "travel_mode 必須是 DRIVE 或 TWO_WHEELER",
                f"{path}.travel_mode",
            )
        mode_counts[str(mode)] += 1
        sample_date = _nonempty_string(sample["date"], f"{path}.date")
        try:
            parsed_sample_date = date.fromisoformat(sample_date)
        except ValueError as exc:
            raise InputError(
                "INVALID_PLAN", "date 必須是 YYYY-MM-DD", f"{path}.date"
            ) from exc
        sample_dates.add(sample_date)
        departure_text = _nonempty_string(
            sample["departure_time"], f"{path}.departure_time"
        )
        try:
            departure = datetime.fromisoformat(departure_text)
        except ValueError as exc:
            raise InputError(
                "INVALID_PLAN",
                "departure_time 必須是 ISO 8601 date-time",
                f"{path}.departure_time",
            ) from exc
        if departure.tzinfo is None or departure.utcoffset() is None:
            raise InputError(
                "INVALID_PLAN",
                "departure_time 必須包含 UTC offset",
                f"{path}.departure_time",
            )
        if departure <= now.astimezone(departure.tzinfo):
            raise InputError(
                "PLAN_EXPIRED",
                "plan 含有已到期的 departure_time；請重新執行 plan",
                f"{path}.departure_time",
            )
        if departure.date() != parsed_sample_date:
            raise InputError(
                "INVALID_PLAN",
                "date 必須與 departure_time 的本地日期一致",
                f"{path}.date",
            )
        definition = journey_definitions.setdefault(
            journey_id,
            {"label": journey_label, "directions": {}},
        )
        if definition["label"] != journey_label:
            raise InputError(
                "INVALID_PLAN",
                "同一 journey_id 的 label 必須一致",
                f"{path}.journey_label",
            )
        directions = definition["directions"]
        assert isinstance(directions, dict)
        point_labels = [point["label"] for point in points]
        if direction in directions and directions[direction] != point_labels:
            raise InputError(
                "INVALID_PLAN",
                "同一 Journey direction 的 Points 必須一致",
                f"{path}.points",
            )
        directions[direction] = point_labels

    preview = _require_object(plan["preview"], "$.preview")
    _validate_v2_preview(
        preview,
        samples=samples,
        planned_leg_count=planned_leg_count,
        mode_counts=mode_counts,
        journey_definitions=journey_definitions,
    )
    _validate_v2_schedule(
        plan["schedule"],
        sample_dates=sample_dates,
        mode_counts=mode_counts,
        samples=samples,
        journey_ids=set(journey_definitions),
    )
    return dict(plan)


def _validate_input_compatibility(value: object) -> None:
    compatibility = _require_object(value, "$.input_compatibility")
    _reject_unknown(
        compatibility,
        {"config_schema_version", "plan_request_schema_version", "adapter"},
        "$.input_compatibility",
    )
    _require_fields(
        compatibility,
        {"config_schema_version", "plan_request_schema_version", "adapter"},
        "$.input_compatibility",
        "INVALID_PLAN",
    )
    pair = (
        compatibility["config_schema_version"],
        compatibility["plan_request_schema_version"],
        compatibility["adapter"],
    )
    if pair not in {("1", "1", "v1_to_v2"), ("2", "2", None)}:
        raise InputError(
            "INVALID_PLAN",
            "input_compatibility 與 adapter 不一致",
            "$.input_compatibility",
        )


def _validate_plan_dependency(value: object) -> None:
    dependency = _require_object(value, "$.dependency")
    _reject_unknown(
        dependency,
        {
            "path",
            "skill_version",
            "cli_contract_version",
            "schema_version",
            "travel_modes",
            "output_profile",
            "itinerary_limits",
        },
        "$.dependency",
    )
    _require_fields(
        dependency,
        {
            "path",
            "skill_version",
            "cli_contract_version",
            "schema_version",
            "travel_modes",
            "output_profile",
            "itinerary_limits",
        },
        "$.dependency",
        "INVALID_PLAN",
    )
    _nonempty_string(dependency["path"], "$.dependency.path")
    version = _nonempty_string(dependency["skill_version"], "$.dependency.skill_version")
    if version.split(".", 1)[0] != "2":
        raise InputError(
            "INVALID_PLAN", "skill_version major 必須是 2", "$.dependency.skill_version"
        )
    expected = {
        "cli_contract_version": "2.0.0",
        "schema_version": "2",
        "travel_modes": ["DRIVE", "TWO_WHEELER"],
        "output_profile": "itinerary_summary",
    }
    for key, expected_value in expected.items():
        if dependency[key] != expected_value:
            raise InputError(
                "INVALID_PLAN", f"{key} 不相容", f"$.dependency.{key}"
            )
    limits = _require_object(dependency["itinerary_limits"], "$.dependency.itinerary_limits")
    required_limits = {
        "minimum_points": 2,
        "maximum_points": 12,
        "maximum_intermediate_waypoints": 10,
        "waypoint_order": "fixed",
    }
    if limits != required_limits:
        raise InputError(
            "INVALID_PLAN",
            "itinerary_limits 不相容",
            "$.dependency.itinerary_limits",
        )


def _validate_resolved_points(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 12:
        raise InputError("INVALID_PLAN", "points 必須包含 2 到 12 個項目", path)
    points: list[dict[str, object]] = []
    labels: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        point = _require_object(item, item_path)
        _reject_unknown(point, {"label", "location"}, item_path)
        _require_fields(
            point, {"label", "location"}, item_path, "INVALID_PLAN"
        )
        label = _label(point["label"], f"{item_path}.label", "INVALID_PLAN")
        if label in labels:
            raise InputError(
                "INVALID_PLAN", "Point label 不得重複", f"{item_path}.label"
            )
        labels.add(label)
        points.append(
            {
                "label": label,
                "location": _validate_location(
                    point["location"], f"{item_path}.location"
                ),
            }
        )
    return points


def _validate_v2_preview(
    preview: Mapping[str, object],
    *,
    samples: list[object],
    planned_leg_count: int,
    mode_counts: Mapping[str, int],
    journey_definitions: Mapping[str, dict[str, object]],
) -> None:
    allowed = {
        "journey_count",
        "request_count",
        "planned_leg_count",
        "retry_limit",
        "maximum_http_requests",
        "rate_limit_qpm",
        "local_rate_limit_only",
        "confirmation_threshold",
        "confirmation_required",
        "estimated_sku_requests",
        "journeys",
    }
    _reject_unknown(preview, allowed, "$.preview")
    _require_fields(preview, allowed, "$.preview", "INVALID_PLAN")
    request_count = len(samples)
    checks = {
        "journey_count": len(journey_definitions),
        "request_count": request_count,
        "planned_leg_count": planned_leg_count,
        "retry_limit": 2,
        "maximum_http_requests": request_count * 3,
        "local_rate_limit_only": True,
    }
    for key, expected in checks.items():
        if preview[key] != expected:
            raise InputError(
                "INVALID_PLAN", f"{key} 與 samples 不一致", f"$.preview.{key}"
            )
    _bounded_int(preview["rate_limit_qpm"], "$.preview.rate_limit_qpm", 1, 3000)
    threshold = _bounded_int(
        preview["confirmation_threshold"],
        "$.preview.confirmation_threshold",
        1,
        1000,
    )
    if preview["confirmation_required"] is not (request_count > threshold):
        raise InputError(
            "INVALID_PLAN",
            "confirmation_required 與 request_count 不一致",
            "$.preview.confirmation_required",
        )
    expected_sku = {
        "routes_compute_pro": mode_counts["DRIVE"],
        "routes_compute_enterprise": mode_counts["TWO_WHEELER"],
    }
    if preview["estimated_sku_requests"] != expected_sku:
        raise InputError(
            "INVALID_PLAN",
            "estimated_sku_requests 與 samples 不一致",
            "$.preview.estimated_sku_requests",
        )
    expected_journeys = []
    for journey_id, definition in journey_definitions.items():
        directions = definition["directions"]
        assert isinstance(directions, dict)
        if set(directions) != {"outbound", "return"}:
            raise InputError(
                "INVALID_PLAN",
                "每個 Journey 必須同時包含 outbound 與 return",
                "$.samples",
            )
        expected_directions = []
        for direction in ("outbound", "return"):
            labels = directions[direction]
            assert isinstance(labels, list)
            expected_directions.append(
                {
                    "direction": direction,
                    "point_labels": labels,
                    "point_count": len(labels),
                    "intermediate_count": len(labels) - 2,
                    "leg_count": len(labels) - 1,
                }
            )
        expected_journeys.append(
            {
                "journey_id": journey_id,
                "journey_label": definition["label"],
                "directions": expected_directions,
            }
        )
    if preview["journeys"] != expected_journeys:
        raise InputError(
            "INVALID_PLAN", "journeys preview 與 samples 不一致", "$.preview.journeys"
        )


def _validate_v2_schedule(
    value: object,
    *,
    sample_dates: set[str],
    mode_counts: Mapping[str, int],
    samples: list[object],
    journey_ids: set[str],
) -> None:
    schedule = _require_object(value, "$.schedule")
    allowed = {
        "start_date",
        "end_date",
        "weeks",
        "weekdays",
        "dates",
        "utc_offset",
        "outbound_departure_time",
        "return_departure_time",
        "travel_modes",
    }
    _reject_unknown(schedule, allowed, "$.schedule")
    _require_fields(schedule, allowed, "$.schedule", "INVALID_PLAN")
    weeks = _bounded_int(schedule["weeks"], "$.schedule.weeks", 1, 4)
    weekdays = _weekdays_at_path(schedule["weekdays"], "$.schedule.weekdays")
    offset = _parse_utc_offset(schedule["utc_offset"], "$.schedule.utc_offset")
    outbound_time = _local_time(
        schedule["outbound_departure_time"],
        "$.schedule.outbound_departure_time",
    )
    return_time = _local_time(
        schedule["return_departure_time"], "$.schedule.return_departure_time"
    )
    modes = _travel_modes(schedule["travel_modes"], "$.schedule.travel_modes")
    actual_modes = {mode for mode, count in mode_counts.items() if count}
    if set(modes) != actual_modes:
        raise InputError(
            "INVALID_PLAN",
            "travel_modes 與 samples 不一致",
            "$.schedule.travel_modes",
        )
    dates_value = schedule["dates"]
    if (
        not isinstance(dates_value, list)
        or any(not isinstance(item, str) for item in dates_value)
        or dates_value != sorted(sample_dates)
    ):
        raise InputError("INVALID_PLAN", "dates 與 samples 不一致", "$.schedule.dates")
    try:
        schedule_start = date.fromisoformat(
            _nonempty_string(schedule["start_date"], "$.schedule.start_date")
        )
        schedule_end = date.fromisoformat(
            _nonempty_string(schedule["end_date"], "$.schedule.end_date")
        )
    except ValueError as exc:
        raise InputError(
            "INVALID_PLAN", "start_date 與 end_date 必須是 YYYY-MM-DD", "$.schedule"
        ) from exc
    if schedule_end != schedule_start + timedelta(days=weeks * 7 - 1):
        raise InputError(
            "INVALID_PLAN", "end_date 與 weeks 不一致", "$.schedule.end_date"
        )
    if any(
        not schedule_start <= date.fromisoformat(item) <= schedule_end
        for item in dates_value
    ):
        raise InputError("INVALID_PLAN", "dates 超出 schedule 範圍", "$.schedule.dates")
    parsed_dates = {date.fromisoformat(item) for item in dates_value}
    if any(item.isoweekday() not in weekdays for item in parsed_dates):
        raise InputError(
            "INVALID_PLAN", "dates 與 weekdays 不一致", "$.schedule.dates"
        )

    actual_combinations: set[tuple[str, str, str, str]] = set()
    expected_offset = offset.utcoffset(None)
    for index, sample_value in enumerate(samples):
        sample = _require_object(sample_value, f"$.samples[{index}]")
        direction = str(sample["direction"])
        departure = datetime.fromisoformat(str(sample["departure_time"]))
        expected_time = outbound_time if direction == "outbound" else return_time
        if departure.utcoffset() != expected_offset or departure.time().replace(
            tzinfo=None
        ) != expected_time:
            raise InputError(
                "INVALID_PLAN",
                "departure_time 與 schedule 不一致",
                f"$.samples[{index}].departure_time",
            )
        combination = (
            str(sample["date"]),
            str(sample["journey_id"]),
            direction,
            str(sample["travel_mode"]),
        )
        if combination in actual_combinations:
            raise InputError(
                "INVALID_PLAN",
                "Journey/date/direction/mode 組合不得重複",
                f"$.samples[{index}]",
            )
        actual_combinations.add(combination)
    expected_combinations = {
        (sample_date, journey_id, direction, mode)
        for sample_date in dates_value
        for journey_id in journey_ids
        for direction in ("outbound", "return")
        for mode in modes
    }
    if actual_combinations != expected_combinations:
        raise InputError(
            "INVALID_PLAN",
            "samples 未完整涵蓋 schedule 與 Journeys",
            "$.samples",
        )


def _validate_config(value: object) -> dict[str, object]:
    config = _require_object(value, "$config")
    if config.get("schema_version") == "1":
        return _validate_v1_config(config)
    if config.get("schema_version") == "2":
        return _validate_v2_config(config)
    raise InputError(
        "INVALID_CONFIG",
        "schema_version 必須是 1 或 2",
        "$config.schema_version",
    )


def _validate_v1_config(config: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown(
        config,
        {
            "schema_version",
            "home",
            "companies",
            "utc_offset",
            "morning_departure_time",
            "evening_departure_time",
        },
        "$config",
    )
    required = {
        "schema_version",
        "home",
        "companies",
        "utc_offset",
        "morning_departure_time",
        "evening_departure_time",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise InputError("INVALID_CONFIG", "缺少必要欄位", f"$config.{missing[0]}")
    if config["schema_version"] != "1":
        raise InputError("INVALID_CONFIG", "schema_version 必須是 1", "$config.schema_version")
    home = _validate_endpoint(config["home"], "$config.home")
    companies_value = config["companies"]
    if not isinstance(companies_value, list) or not companies_value:
        raise InputError("INVALID_CONFIG", "companies 必須是非空 array", "$config.companies")
    companies = [
        _validate_company(item, f"$config.companies[{index}]")
        for index, item in enumerate(companies_value)
    ]
    _reject_duplicate_company_ids(companies)
    _parse_utc_offset(config["utc_offset"], "$config.utc_offset")
    _local_time(config["morning_departure_time"], "$config.morning_departure_time")
    _local_time(config["evening_departure_time"], "$config.evening_departure_time")
    return {
        **config,
        "home": home,
        "companies": companies,
    }


def _validate_endpoint(value: object, path: str) -> dict[str, object]:
    endpoint = _require_object(value, path)
    _reject_unknown(endpoint, {"label", "location"}, path)
    label = _nonempty_string(endpoint.get("label"), f"{path}.label")
    return {"label": label, "location": _validate_location(endpoint.get("location"), f"{path}.location")}


def _validate_company(value: object, path: str) -> dict[str, object]:
    company = _require_object(value, path)
    _reject_unknown(company, {"id", "name", "location"}, path)
    company_id = _nonempty_string(company.get("id"), f"{path}.id")
    if not SAFE_ID.fullmatch(company_id):
        raise InputError("INVALID_INPUT", "id 必須是安全識別符", f"{path}.id")
    return {
        "id": company_id,
        "name": _nonempty_string(company.get("name"), f"{path}.name"),
        "label": company_id,
        "location": _validate_location(company.get("location"), f"{path}.location"),
    }


def _validate_location(value: object, path: str) -> dict[str, str]:
    location = _require_object(value, path)
    _reject_unknown(location, {"address", "place_id"}, path)
    present = [key for key in ("address", "place_id") if key in location]
    if len(present) != 1:
        raise InputError("INVALID_INPUT", "必須且只能提供 address 或 place_id", path)
    key = present[0]
    return {key: _nonempty_string(location[key], f"{path}.{key}")}


def _reject_duplicate_company_ids(companies: list[dict[str, object]]) -> None:
    seen: set[str] = set()
    for index, company in enumerate(companies):
        company_id = str(company["id"])
        if company_id in seen:
            raise InputError("INVALID_INPUT", "company id 不得重複", f"$.companies[{index}].id")
        seen.add(company_id)


def _parse_utc_offset(value: object, path: str) -> timezone:
    text = _nonempty_string(value, path)
    match = UTC_OFFSET.fullmatch(text)
    if not match:
        raise InputError("INVALID_INPUT", "必須是明確 UTC offset，例如 +08:00", path)
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise InputError("INVALID_INPUT", "UTC offset 超出範圍", path)
    total = hours * 60 + minutes
    if match.group(1) == "-":
        total = -total
    return timezone(timedelta(minutes=total))


def _local_time(value: object, path: str) -> time:
    text = _nonempty_string(value, path)
    match = LOCAL_TIME.fullmatch(text)
    if not match:
        raise InputError("INVALID_INPUT", "時間必須使用 HH:MM", path)
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        raise InputError("INVALID_INPUT", "時間超出範圍", path)
    return time(hours, minutes)


def _plan_start_date(value: object, today: date) -> date:
    if value is None:
        days_until_next_monday = (7 - today.weekday()) % 7
        if days_until_next_monday == 0:
            days_until_next_monday = 7
        return today + timedelta(days=days_until_next_monday)
    text = _nonempty_string(value, "$.start_date")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InputError("INVALID_INPUT", "必須是 YYYY-MM-DD", "$.start_date") from exc


def _weekdays(value: object) -> list[int]:
    return _weekdays_at_path(value, "$.weekdays")


def _weekdays_at_path(value: object, path: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise InputError("INVALID_INPUT", "weekdays 必須是非空 array", path)
    if any(type(item) is not int or not 1 <= item <= 7 for item in value):
        raise InputError("INVALID_INPUT", "weekdays 必須是 1 到 7", path)
    if len(set(value)) != len(value):
        raise InputError("INVALID_INPUT", "weekdays 不得重複", path)
    return sorted(value)


def _travel_modes(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InputError("INVALID_INPUT", "travel_modes 必須是非空 array", path)
    if any(item not in {"DRIVE", "TWO_WHEELER"} for item in value):
        raise InputError("INVALID_INPUT", "只支援 DRIVE 與 TWO_WHEELER", path)
    if len(set(value)) != len(value):
        raise InputError("INVALID_INPUT", "travel_modes 不得重複", path)
    return list(value)


def _bounded_int(value: object, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError("INVALID_INPUT", f"必須是 {minimum} 到 {maximum} 的整數", path)
    return value


def _require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InputError("INVALID_INPUT", "必須是 object", path)
    return dict(value)


def _reject_unknown(value: Mapping[str, object], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InputError("INVALID_INPUT", "未知欄位", f"{path}.{unknown[0]}")


def _nonempty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError("INVALID_INPUT", "必須是非空字串", path)
    return value.strip()


def _content_id(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def default_private_paths(
    *, platform_name: str, environ: Mapping[str, str], home: Path
) -> dict[str, Path]:
    if platform_name == "win32":
        config_base = home / ".config"
        data_base = home / ".local" / "share"
    elif platform_name == "darwin":
        config_base = home / "Library" / "Application Support"
        data_base = config_base
    else:
        config_base = Path(environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        data_base = Path(environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    relative = Path("command1264-skills") / "commute-analyzer"
    config = Path(
        environ.get(
            "COMMUTE_ANALYZER_CONFIG",
            str(config_base / relative / "config.json"),
        )
    )
    data = data_base / relative
    return {
        "config": config,
        "data": data,
        "reports": data / "reports",
        "ledger": data / "usage.jsonl",
    }


def legacy_windows_private_paths(
    *, environ: Mapping[str, str], home: Path
) -> dict[str, Path]:
    config_base = Path(environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    data_base = Path(environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    relative = Path("command1264-skills") / "commute-analyzer"
    data = data_base / relative
    return {
        "config": config_base / relative / "config.json",
        "data": data,
        "reports": data / "reports",
        "ledger": data / "usage.jsonl",
    }


def resolve_private_config(
    *, platform_name: str, environ: Mapping[str, str], home: Path
) -> dict[str, object]:
    default_environ = {
        key: value
        for key, value in environ.items()
        if key != "COMMUTE_ANALYZER_CONFIG"
    }
    default_path = default_private_paths(
        platform_name=platform_name,
        environ=default_environ,
        home=home,
    )["config"]
    override = environ.get("COMMUTE_ANALYZER_CONFIG")
    legacy_path = None
    if platform_name == "win32":
        legacy_path = legacy_windows_private_paths(environ=environ, home=home)["config"]
    if override:
        path = Path(override)
        source = "environment_override"
        migration_required = False
        warnings: list[dict[str, str]] = []
    elif default_path.is_file() or legacy_path is None or not legacy_path.is_file():
        path = default_path
        source = "cross_runtime_default"
        migration_required = False
        warnings = []
    else:
        path = legacy_path
        source = "legacy_windows_appdata"
        migration_required = True
        warnings = [
            {
                "code": "legacy_windows_appdata_path",
                "message": (
                    "目前使用舊 Windows AppData config；"
                    "請人工移至跨 runtime 預設路徑"
                ),
            }
        ]
    return {
        "path": path,
        "default_path": default_path,
        "source": source,
        "configured": path.is_file(),
        "migration_required": migration_required,
        "legacy_path": legacy_path,
        "warnings": warnings,
    }


def _config_metadata(resolution: Mapping[str, object]) -> dict[str, object]:
    return {
        "path": str(resolution["path"]),
        "default_path": str(resolution["default_path"]),
        "source": resolution["source"],
        "configured": resolution["configured"],
        "migration_required": resolution["migration_required"],
        "legacy_path": (
            str(resolution["legacy_path"])
            if resolution["legacy_path"] is not None
            else None
        ),
        "warnings": resolution["warnings"],
    }


def _print_config_warnings(
    resolution: Mapping[str, object], stderr: TextIO
) -> None:
    warnings = resolution.get("warnings")
    if not isinstance(warnings, list):
        return
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        print(
            f"Config warning [{warning.get('code')}]: {warning.get('message')}",
            file=stderr,
        )


def capabilities() -> dict[str, object]:
    return {
        "skill_name": "commute-analyzer",
        "skill_version": SKILL_VERSION,
        "cli_contract_version": CLI_CONTRACT_VERSION,
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
    }


def _write_json(stream: TextIO, value: object) -> None:
    json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
    stream.write("\n")


def _call_dependency(
    runner: Callable[[Path, str, object, dict[str, str]], tuple[int, str, str]],
    skill_path: Path,
    command: str,
    payload: object,
    environ: dict[str, str],
) -> tuple[int, str, str]:
    try:
        return runner(skill_path, command, payload, environ)
    except OSError as error:
        raise InputError(
            "GOOGLE_ROUTES_PROCESS_FAILED",
            "無法啟動 google-routes；請確認 Python 與 Skill 安裝後重新執行 plan",
            "$.dependency",
        ) from error


def run_cli(
    argv: list[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    environ: Mapping[str, str],
    cwd: Path | None = None,
    home: Path | None = None,
    platform_name: str | None = None,
    now: datetime | None = None,
    dependency_runner: Callable[
        [Path, str, object, dict[str, str]], tuple[int, str, str]
    ] | None = None,
) -> int:
    if argv == ["capabilities"]:
        _write_json(stdout, capabilities())
        return 0
    if argv == ["config", "path"]:
        resolution = resolve_private_config(
            platform_name=sys.platform if platform_name is None else platform_name,
            environ=environ,
            home=Path.home() if home is None else home,
        )
        _write_json(
            stdout,
            {
                "schema_version": "1",
                "config": _config_metadata(resolution),
            },
        )
        return 0
    if argv == ["config", "check"]:
        resolution = resolve_private_config(
            platform_name=sys.platform if platform_name is None else platform_name,
            environ=environ,
            home=Path.home() if home is None else home,
        )
        try:
            config = _validate_config(_read_json_file(Path(resolution["path"])))
        except InputError as error:
            return _write_input_error(error, stdout, stderr)
        metadata = _config_metadata(resolution)
        metadata["content_schema_version"] = config["schema_version"]
        metadata["schema_migration"] = {
            "target_schema_version": "2",
            "recommended": config["schema_version"] == "1",
            "automatic": False,
        }
        _write_json(stdout, {"schema_version": "2", "config": metadata})
        _print_config_warnings(resolution, stderr)
        print("私人通勤設定有效。", file=stderr)
        return 0
    if argv and argv[0] == "plan":
        config_argument: str | None = None
        config_resolution: dict[str, object] | None = None
        if len(argv) == 3 and argv[1] == "--config":
            config_argument = argv[2]
        elif len(argv) != 1:
            return _write_usage_error(stdout, stderr)
        try:
            request_value = _read_json(stdin, "plan request")
            effective_home = Path.home() if home is None else home
            effective_cwd = Path.cwd() if cwd is None else cwd
            effective_platform = sys.platform if platform_name is None else platform_name
            if config_argument:
                config_path = Path(config_argument)
            else:
                config_resolution = resolve_private_config(
                    platform_name=effective_platform,
                    environ=environ,
                    home=effective_home,
                )
                config_path = Path(config_resolution["path"])
            config_value = _read_json_file(config_path)
            commute_skill_dir = Path(__file__).resolve().parents[1]
            dependency_path = discover_google_routes(
                environ=environ,
                commute_skill_dir=commute_skill_dir,
                cwd=effective_cwd,
                home=effective_home,
            )
            runner = _run_google_routes if dependency_runner is None else dependency_runner
            exit_code, dependency_stdout, _ = _call_dependency(
                runner, dependency_path, "capabilities", None, dict(environ)
            )
            if exit_code != 0:
                raise InputError(
                    "GOOGLE_ROUTES_INCOMPATIBLE",
                    "google-routes capabilities 執行失敗。請更新 google-routes："
                    + INSTALL_COMMAND,
                )
            try:
                dependency_capabilities = json.loads(dependency_stdout)
            except json.JSONDecodeError as exc:
                raise InputError(
                    "GOOGLE_ROUTES_INCOMPATIBLE",
                    "google-routes capabilities 未回傳有效 JSON。請更新 google-routes："
                    + INSTALL_COMMAND,
                ) from exc
            dependency = validate_google_routes_capabilities(
                dependency_capabilities, dependency_path
            )
            plan = build_plan(
                request_value,
                config_value,
                dependency,
                now=datetime.now(timezone.utc) if now is None else now,
            )
        except InputError as error:
            return _write_input_error(error, stdout, stderr)
        _write_json(stdout, plan)
        if config_resolution is not None:
            _print_config_warnings(config_resolution, stderr)
        print(
            "計畫已建立，不會呼叫 Routes API："
            f"{plan['preview']['request_count']} 筆 request。",
            file=stderr,
        )
        return 0
    if argv and argv[0] == "run":
        try:
            output_argument, confirmed_plan_id = _parse_run_arguments(argv[1:])
            effective_home = Path.home() if home is None else home
            effective_cwd = Path.cwd() if cwd is None else cwd
            effective_platform = sys.platform if platform_name is None else platform_name
            effective_now = datetime.now(timezone.utc) if now is None else now
            plan = validate_execution_plan(
                _read_json(stdin, "execution plan"), now=effective_now
            )
            preview = _require_object(plan["preview"], "$.preview")
            if preview.get("confirmation_required") is True:
                if confirmed_plan_id != plan["plan_id"]:
                    raise InputError(
                        "PLAN_CONFIRMATION_REQUIRED",
                        "request 數超過門檻；請以 --confirm-plan-id 確認同一個 plan_id",
                        "$.plan_id",
                    )
            dependency = _require_object(plan["dependency"], "$.dependency")
            dependency_path = Path(
                _nonempty_string(dependency.get("path"), "$.dependency.path")
            )
            resolved_dependency_path = discover_google_routes(
                environ=environ,
                commute_skill_dir=Path(__file__).resolve().parents[1],
                cwd=effective_cwd,
                home=effective_home,
            )
            if resolved_dependency_path != dependency_path.resolve():
                raise InputError(
                    "PLAN_DEPENDENCY_CHANGED",
                    "目前解析的 google-routes 路徑與 plan 不同；請重新執行 plan",
                    "$.dependency.path",
                )
            dependency_path = resolved_dependency_path
            runner = _run_google_routes if dependency_runner is None else dependency_runner
            environment = dict(environ)
            cap_exit, cap_stdout, _ = _call_dependency(
                runner, dependency_path, "capabilities", None, environment
            )
            if cap_exit != 0:
                raise InputError(
                    "GOOGLE_ROUTES_INCOMPATIBLE",
                    "google-routes capabilities 執行失敗；請重新執行 plan",
                    "$.dependency",
                )
            try:
                current_capabilities = json.loads(cap_stdout)
            except json.JSONDecodeError as exc:
                raise InputError(
                    "GOOGLE_ROUTES_INCOMPATIBLE",
                    "google-routes capabilities 未回傳有效 JSON",
                    "$.dependency",
                ) from exc
            current_dependency = validate_google_routes_capabilities(
                current_capabilities, dependency_path
            )
            if current_dependency != dependency:
                raise InputError(
                    "PLAN_DEPENDENCY_CHANGED",
                    "google-routes 能力或路徑已改變；請重新執行 plan",
                    "$.dependency",
                )
            query = _route_query_from_plan(plan)
            query_exit, query_stdout, _ = _call_dependency(
                runner, dependency_path, "query", query, environment
            )
            if query_exit not in {0, 3, 4}:
                raise InputError(
                    "GOOGLE_ROUTES_EXECUTION_FAILED",
                    "google-routes query 未回傳可分析結果",
                    "$dependency",
                )
            try:
                route_result = json.loads(query_stdout)
            except json.JSONDecodeError as exc:
                raise InputError(
                    "GOOGLE_ROUTES_EXECUTION_FAILED",
                    "google-routes query 未回傳有效 JSON",
                    "$dependency",
                ) from exc
            analysis = analyze_route_results(plan, route_result, now=effective_now)
            private_paths = default_private_paths(
                platform_name=effective_platform,
                environ=environ,
                home=effective_home,
            )
            outputs = write_private_outputs(
                analysis,
                plan,
                output_dir=Path(output_argument) if output_argument else private_paths["reports"],
                ledger_path=private_paths["ledger"],
                now=effective_now,
            )
            result = {**analysis, "outputs": outputs}
        except InputError as error:
            return _write_input_error(error, stdout, stderr)
        _write_json(stdout, result)
        print(
            "通勤分析完成："
            f"{result['request_summary']['success']} 成功、"
            f"{result['request_summary']['degraded']} 降級、"
            f"{result['request_summary']['failed']} 失敗。",
            file=stderr,
        )
        return {"success": 0, "partial_success": 3, "failure": 4}[str(result["status"])]
    return _write_usage_error(stdout, stderr)


def _parse_run_arguments(arguments: list[str]) -> tuple[str | None, str | None]:
    output_dir: str | None = None
    confirmed_plan_id: str | None = None
    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option not in {"--output-dir", "--confirm-plan-id"} or index + 1 >= len(arguments):
            raise InputError("USAGE_ERROR", "run 參數無效", "$command")
        value = arguments[index + 1]
        if option == "--output-dir":
            if output_dir is not None:
                raise InputError("USAGE_ERROR", "--output-dir 不得重複", "$command")
            output_dir = value
        else:
            if confirmed_plan_id is not None:
                raise InputError("USAGE_ERROR", "--confirm-plan-id 不得重複", "$command")
            confirmed_plan_id = value
        index += 2
    return output_dir, confirmed_plan_id


def _route_query_from_plan(plan: Mapping[str, object]) -> dict[str, object]:
    preview = _require_object(plan.get("preview"), "$.preview")
    samples = plan.get("samples")
    assert isinstance(samples, list)
    requests: list[dict[str, object]] = []
    for sample_value in samples:
        sample = _require_object(sample_value, "$.samples[]")
        requests.append(
            {
                "request_id": sample["request_id"],
                "points": copy.deepcopy(sample["points"]),
                "travel_mode": sample["travel_mode"],
                "departure_time": sample["departure_time"],
            }
        )
    return {
        "schema_version": "2",
        "profile": "itinerary_summary",
        "rate_limit_qpm": preview["rate_limit_qpm"],
        "requests": requests,
    }


def analyze_route_results(
    plan: Mapping[str, object], route_value: object, *, now: datetime
) -> dict[str, object]:
    schedule = _require_object(plan.get("schedule"), "$.schedule")
    weeks = _bounded_int(schedule.get("weeks"), "$.schedule.weeks", 1, 4)
    route = _require_object(route_value, "$route_result")
    if (
        route.get("schema_version") != "2"
        or route.get("cli_contract_version") != "2.0.0"
        or route.get("profile") != "itinerary_summary"
    ):
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "google-routes itinerary result contract 不相容",
            "$route_result",
        )
    if route.get("status") not in {
        "success",
        "degraded",
        "partial_success",
        "failure",
    }:
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "google-routes result status 不相容",
            "$route_result.status",
        )
    results_value = route.get("results")
    if not isinstance(results_value, list):
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "results 必須是 array",
            "$route_result.results",
        )
    result_by_id: dict[str, tuple[int, dict[str, object]]] = {}
    for index, result_value in enumerate(results_value):
        path = f"$route_result.results[{index}]"
        result = _require_object(result_value, path)
        request_id = _nonempty_string(result.get("request_id"), f"{path}.request_id")
        if request_id in result_by_id:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "request_id 不得重複",
                f"{path}.request_id",
            )
        result_by_id[request_id] = (index, result)

    samples_value = plan.get("samples")
    assert isinstance(samples_value, list)
    expected_ids = {
        str(sample["request_id"])
        for sample in samples_value
        if isinstance(sample, dict)
    }
    if set(result_by_id) != expected_ids:
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "result request_id 集合與 plan 不一致",
            "$route_result.results",
        )

    normalized_samples: list[dict[str, object]] = []
    for sample_index, sample_value in enumerate(samples_value):
        sample = _require_object(sample_value, f"$.samples[{sample_index}]")
        result_index, provider = result_by_id[str(sample["request_id"])]
        result_path = f"$route_result.results[{result_index}]"
        status = provider.get("status")
        if status not in {"success", "degraded", "error"}:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "未知 route status",
                f"{result_path}.status",
            )
        if provider.get("travel_mode") != sample.get("travel_mode"):
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "result travel_mode 與 plan 不一致",
                f"{result_path}.travel_mode",
            )
        attempts = provider.get("attempts")
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "attempts 必須是 1 到 3 的整數",
                f"{result_path}.attempts",
            )
        normalized: dict[str, object] = {
            "request_id": sample["request_id"],
            "journey_id": sample["journey_id"],
            "journey_label": sample["journey_label"],
            "date": sample["date"],
            "direction": sample["direction"],
            "travel_mode": sample["travel_mode"],
            "status": status,
            "attempts": attempts,
        }
        if status in {"success", "degraded"}:
            distance = _provider_number(
                provider.get("distance_meters"), f"{result_path}.distance_meters"
            )
            duration = _provider_number(
                provider.get("duration_seconds"), f"{result_path}.duration_seconds"
            )
            static_duration = _provider_number(
                provider.get("static_duration_seconds"),
                f"{result_path}.static_duration_seconds",
            )
            warnings = provider.get("warnings")
            if not isinstance(warnings, list) or any(
                not isinstance(item, str) for item in warnings
            ):
                raise InputError(
                    "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                    "warnings 必須是 string array",
                    f"{result_path}.warnings",
                )
            fallback = _safe_fallback(provider.get("fallback"), result_path)
            planned_points = sample["points"]
            assert isinstance(planned_points, list)
            expected_labels = [str(point["label"]) for point in planned_points]
            _validate_provider_points(
                provider.get("points"), expected_labels, result_path
            )
            legs = _normalize_provider_legs(
                provider.get("legs"), expected_labels, result_path
            )
            totals = (
                sum(float(leg["distance_meters"]) for leg in legs),
                sum(float(leg["duration_seconds"]) for leg in legs),
                sum(float(leg["static_duration_seconds"]) for leg in legs),
            )
            if any(
                abs(actual - expected) > 1e-9
                for actual, expected in zip(
                    totals,
                    (float(distance), float(duration), float(static_duration)),
                    strict=True,
                )
            ):
                raise InputError(
                    "DEPENDENCY_LEG_MISMATCH",
                    "google-routes 的 route totals 與 legs 不一致",
                    f"{result_path}.legs",
                )
            normalized.update(
                {
                    "distance_meters": distance,
                    "duration_seconds": duration,
                    "static_duration_seconds": static_duration,
                    "legs": legs,
                    "warnings": list(warnings),
                    "fallback": fallback,
                }
            )
        else:
            provider_error = provider.get("error")
            error_value = provider_error if isinstance(provider_error, dict) else {}
            safe_error: dict[str, object] = {
                "code": error_value.get("code")
                if isinstance(error_value.get("code"), str)
                and str(error_value.get("code")).strip()
                else "UNKNOWN",
                "retryable": error_value.get("retryable") is True,
            }
            http_status = error_value.get("http_status")
            if type(http_status) is int and 300 <= http_status <= 599:
                safe_error["http_status"] = http_status
            normalized["error"] = safe_error
        normalized_samples.append(normalized)

    journeys: list[dict[str, object]] = []
    journey_order: list[tuple[str, str]] = []
    for sample in normalized_samples:
        identity = (str(sample["journey_id"]), str(sample["journey_label"]))
        if identity not in journey_order:
            journey_order.append(identity)
    for journey_id, journey_label in journey_order:
        journey_samples = [
            item for item in normalized_samples if item["journey_id"] == journey_id
        ]
        modes: dict[str, object] = {}
        for mode in ("TWO_WHEELER", "DRIVE"):
            mode_samples = [
                item for item in journey_samples if item["travel_mode"] == mode
            ]
            if not mode_samples:
                continue
            successes = [item for item in mode_samples if item["status"] == "success"]
            outbound = [
                float(item["duration_seconds"])
                for item in successes
                if item["direction"] == "outbound"
            ]
            returns = [
                float(item["duration_seconds"])
                for item in successes
                if item["direction"] == "return"
            ]
            by_date: dict[str, dict[str, float]] = {}
            for item in successes:
                by_date.setdefault(str(item["date"]), {})[
                    str(item["direction"])
                ] = float(item["duration_seconds"])
            round_trips = [
                directions["outbound"] + directions["return"]
                for directions in by_date.values()
                if {"outbound", "return"}.issubset(directions)
            ]
            complete = len(successes) == len(mode_samples)
            weekly_total = sum(round_trips) / weeks
            modes[mode] = {
                "required_sample_count": len(mode_samples),
                "successful_sample_count": len(successes),
                "complete": complete,
                "statistics": {
                    "outbound": _statistics(outbound),
                    "return": _statistics(returns),
                    "daily_round_trip": _statistics(round_trips),
                },
                "weekly_total_seconds": (
                    _clean_number(weekly_total) if complete else None
                ),
                "four_week_month_estimate_seconds": (
                    _clean_number(weekly_total * 4) if complete else None
                ),
                "samples": [
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"journey_id", "journey_label"}
                    }
                    for item in mode_samples
                ],
            }
        motorcycle = modes.get("TWO_WHEELER")
        eligible = isinstance(motorcycle, dict) and motorcycle["complete"] is True
        if eligible:
            reasons: list[str] = []
        elif motorcycle is None:
            reasons = ["未要求機車模式"]
        else:
            reasons = ["機車必要樣本不完整"]
        journeys.append(
            {
                "journey_id": journey_id,
                "journey_label": journey_label,
                "ranking_eligible": eligible,
                "ranking_exclusion_reasons": reasons,
                "modes": modes,
            }
        )

    ranked = [journey for journey in journeys if journey["ranking_eligible"]]
    ranked.sort(
        key=lambda journey: journey["modes"]["TWO_WHEELER"]["statistics"][
            "daily_round_trip"
        ]["average_seconds"]
    )
    ranking = [
        {
            "rank": index,
            "journey_id": journey["journey_id"],
            "journey_label": journey["journey_label"],
            "daily_round_trip_average_seconds": journey["modes"][
                "TWO_WHEELER"
            ]["statistics"]["daily_round_trip"]["average_seconds"],
        }
        for index, journey in enumerate(ranked, start=1)
    ]
    status_counts = {
        status: sum(1 for item in normalized_samples if item["status"] == status)
        for status in ("success", "degraded", "error")
    }
    if status_counts["success"] == len(normalized_samples):
        overall_status = "success"
    elif status_counts["success"] + status_counts["degraded"] > 0:
        overall_status = "partial_success"
    else:
        overall_status = "failure"
    attempts = sum(int(item["attempts"]) for item in normalized_samples)
    return {
        "schema_version": "2",
        "analysis_contract_version": "2.0.0",
        "plan_id": plan["plan_id"],
        "generated_at": now.isoformat(),
        "status": overall_status,
        "dependency_path": plan["dependency"]["path"],
        "request_summary": {
            "planned": len(normalized_samples),
            "actual_http_requests": attempts,
            "retries": max(0, attempts - len(normalized_samples)),
            "success": status_counts["success"],
            "degraded": status_counts["degraded"],
            "failed": status_counts["error"],
        },
        "journeys": journeys,
        "ranking": ranking,
    }


def _provider_number(value: object, path: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "route 數值必須是非負數",
            path,
        )
    return value


def _safe_fallback(value: object, result_path: str) -> dict[str, str] | None:
    if value is None:
        return None
    fallback = _require_object(value, f"{result_path}.fallback")
    return {
        "routing_mode": _nonempty_string(
            fallback.get("routing_mode"), f"{result_path}.fallback.routing_mode"
        ),
        "reason": _nonempty_string(
            fallback.get("reason"), f"{result_path}.fallback.reason"
        ),
    }


def _validate_provider_points(
    value: object, expected_labels: list[str], result_path: str
) -> None:
    if not isinstance(value, list) or len(value) != len(expected_labels):
        raise InputError(
            "DEPENDENCY_LEG_MISMATCH",
            "google-routes 的 Points 數量與 plan 不一致",
            f"{result_path}.points",
        )
    labels = []
    for index, point_value in enumerate(value):
        point = _require_object(point_value, f"{result_path}.points[{index}]")
        labels.append(point.get("label"))
    if labels != expected_labels:
        raise InputError(
            "DEPENDENCY_LEG_MISMATCH",
            "google-routes 的 Point labels 與 plan 不一致",
            f"{result_path}.points",
        )


def _normalize_provider_legs(
    value: object, expected_labels: list[str], result_path: str
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != len(expected_labels) - 1:
        raise InputError(
            "DEPENDENCY_LEG_MISMATCH",
            "google-routes 的 legs 數量與 plan 不一致",
            f"{result_path}.legs",
        )
    legs: list[dict[str, object]] = []
    for index, leg_value in enumerate(value):
        path = f"{result_path}.legs[{index}]"
        leg = _require_object(leg_value, path)
        if (
            leg.get("from_label") != expected_labels[index]
            or leg.get("to_label") != expected_labels[index + 1]
        ):
            raise InputError(
                "DEPENDENCY_LEG_MISMATCH",
                "google-routes 的 leg labels 與 plan 不一致",
                path,
            )
        legs.append(
            {
                "from_label": expected_labels[index],
                "to_label": expected_labels[index + 1],
                "distance_meters": _provider_number(
                    leg.get("distance_meters"), f"{path}.distance_meters"
                ),
                "duration_seconds": _provider_number(
                    leg.get("duration_seconds"), f"{path}.duration_seconds"
                ),
                "static_duration_seconds": _provider_number(
                    leg.get("static_duration_seconds"),
                    f"{path}.static_duration_seconds",
                ),
            }
        )
    return legs


def _statistics(values: list[float]) -> dict[str, int | float] | None:
    if not values:
        return None
    return {
        "average_seconds": _clean_number(statistics.fmean(values)),
        "median_seconds": _clean_number(statistics.median(values)),
        "minimum_seconds": _clean_number(min(values)),
        "maximum_seconds": _clean_number(max(values)),
    }


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def write_private_outputs(
    analysis: Mapping[str, object],
    plan: Mapping[str, object],
    *,
    output_dir: Path,
    ledger_path: Path,
    now: datetime,
) -> dict[str, str]:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        report_id = str(plan["plan_id"]).split(":", 1)[-1][:12]
        stem = f"{now.date().isoformat()}-{report_id}"
        json_path = output_dir / f"{stem}.json"
        markdown_path = output_dir / f"{stem}.md"
        with json_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(analysis, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        markdown_path.write_text(_render_markdown(analysis), encoding="utf-8", newline="\n")
        preview = _require_object(plan.get("preview"), "$.preview")
        schedule = _require_object(plan.get("schedule"), "$.schedule")
        summary = _require_object(analysis.get("request_summary"), "$.request_summary")
        ledger_entry = {
            "schema_version": "2",
            "executed_at": now.isoformat(),
            "plan_id": plan["plan_id"],
            "planned_requests": summary["planned"],
            "actual_http_requests": summary["actual_http_requests"],
            "success": summary["success"],
            "degraded": summary["degraded"],
            "failed": summary["failed"],
            "retries": summary["retries"],
            "travel_modes": schedule["travel_modes"],
            "estimated_sku_requests": preview["estimated_sku_requests"],
        }
        with ledger_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(ledger_entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as error:
        raise InputError(
            "PRIVATE_OUTPUT_FAILED",
            "無法寫入私人報告或 usage ledger",
            "$outputs",
        ) from error
    return {
        "json_report": str(json_path.resolve()),
        "markdown_report": str(markdown_path.resolve()),
        "usage_ledger": str(ledger_path.resolve()),
    }


def _render_markdown(analysis: Mapping[str, object]) -> str:
    lines = [
        "# 預測通勤分析",
        "",
        "> 本報告使用未來 Routes API 預測樣本，不是歷史實際通勤紀錄。",
        "",
    ]
    ranking = analysis.get("ranking")
    if isinstance(ranking, list) and ranking:
        lines.extend(["## 機車通勤排名", ""])
        for item in ranking:
            lines.append(
                f"{item['rank']}. {_markdown_text(item['journey_label'])}："
                f"每日來回平均 {_format_seconds(item['daily_round_trip_average_seconds'])}"
            )
        lines.append("")
    lines.extend(["## 行程結果", ""])
    for journey in analysis.get("journeys", []):
        lines.extend([f"### {_markdown_text(journey['journey_label'])}", ""])
        if not journey["ranking_eligible"]:
            reasons = journey.get("ranking_exclusion_reasons", [])
            explanation = "、".join(str(reason) for reason in reasons)
            lines.append(f"- 排名：不納入（{explanation}）")
        for mode, mode_result in journey["modes"].items():
            lines.append(f"- {mode}：{'完整' if mode_result['complete'] else '不完整'}")
            statistics_value = mode_result["statistics"]
            _append_markdown_statistics(lines, "去程", statistics_value["outbound"])
            _append_markdown_statistics(lines, "回程", statistics_value["return"])
            _append_markdown_statistics(
                lines, "每日來回", statistics_value["daily_round_trip"]
            )
            if mode_result["weekly_total_seconds"] is not None:
                lines.append(f"  - 每週合計：{_format_seconds(mode_result['weekly_total_seconds'])}")
                lines.append(
                    f"  - 四週月估算：{_format_seconds(mode_result['four_week_month_estimate_seconds'])}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_text(value: object) -> str:
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_[\]{}()#+\-.!|>])", r"\\\1", text)


def _append_markdown_statistics(
    lines: list[str], label: str, value: Mapping[str, object] | None
) -> None:
    if value is None:
        return
    lines.append(
        f"  - {label}：平均 {_format_seconds(value['average_seconds'])}；"
        f"中位數 {_format_seconds(value['median_seconds'])}；"
        f"最短 {_format_seconds(value['minimum_seconds'])}；"
        f"最長 {_format_seconds(value['maximum_seconds'])}"
    )


def _format_seconds(value: int | float) -> str:
    minutes = float(value) / 60
    return f"{value} 秒（{minutes:.1f} 分鐘）"


def _run_google_routes(
    skill_path: Path,
    command: str,
    payload: object,
    environ: dict[str, str],
) -> tuple[int, str, str]:
    process = subprocess.run(
        [sys.executable, str(skill_path / "scripts" / "google_routes.py"), command],
        input="" if payload is None else json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=skill_path,
        env=environ,
        check=False,
    )
    return process.returncode, process.stdout, process.stderr


def _read_json(stream: TextIO, label: str) -> object:
    try:
        return json.load(stream)
    except json.JSONDecodeError as error:
        raise InputError(
            "INVALID_JSON",
            f"{label} 不是有效 JSON（第 {error.lineno} 行第 {error.colno} 欄）",
        ) from error


def _read_json_file(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError as error:
        raise InputError(
            "CONFIG_NOT_FOUND",
            "找不到私人設定檔；請執行 config path 查看新預設與 legacy 路徑，"
            "再人工建立或遷移 config",
            "$config",
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise InputError("INVALID_CONFIG", "私人設定檔無法讀取或不是有效 JSON", "$config") from error


def _write_input_error(error: InputError, stdout: TextIO, stderr: TextIO) -> int:
    _write_json(
        stdout,
        {
            "schema_version": "1",
            "error": {
                "code": error.code,
                "path": error.path,
                "message": error.message,
            },
        },
    )
    print(f"輸入或設定錯誤：{error.code}（{error.path}）。", file=stderr)
    return 2


def _write_usage_error(stdout: TextIO, stderr: TextIO) -> int:
    _write_json(
        stdout,
        {
            "schema_version": "1",
            "error": {
                "code": "USAGE_ERROR",
                "path": "$command",
                "message": (
                    "用法：commute_analyzer.py capabilities | config path | "
                    "config check | plan [--config PATH] | run"
                ),
            },
        },
    )
    print("請指定 capabilities、config path、config check、plan 或 run。", file=stderr)
    return 2


def main() -> int:
    return run_cli(
        sys.argv[1:],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        environ=os.environ,
    )


if __name__ == "__main__":
    raise SystemExit(main())
