from __future__ import annotations

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


SKILL_VERSION = "1.1.0"
CLI_CONTRACT_VERSION = "1.0.0"
INSTALL_COMMAND = "npx skills add Command1264/agent-skills --skill google-routes"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
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
    if "1" not in _string_list(capabilities_value.get("schema_versions")):
        problems.append("必須支援 schema version 1")
    modes = set(_string_list(capabilities_value.get("travel_modes")))
    if not {"DRIVE", "TWO_WHEELER"}.issubset(modes):
        problems.append("必須支援 DRIVE 與 TWO_WHEELER")
    if "summary" not in _string_list(capabilities_value.get("output_profiles")):
        problems.append("必須支援 summary profile")
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
        "schema_version": "1",
        "travel_modes": ["DRIVE", "TWO_WHEELER"],
        "output_profile": "summary",
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
    request = _require_object(request_value, "$")
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
    if request.get("schema_version") != "1":
        raise InputError("INVALID_INPUT", "schema_version 必須是 1", "$.schema_version")
    if request.get("schedule_mode", "fixed_departure") != "fixed_departure":
        raise InputError(
            "UNSUPPORTED_SCHEDULE_MODE",
            "v1 只支援 fixed_departure；target_arrival 尚未支援",
            "$.schedule_mode",
        )

    config = _validate_config(config_value)
    offset = _parse_utc_offset(config["utc_offset"], "$.utc_offset")
    local_now = now.astimezone(offset)
    start = _plan_start_date(request.get("start_date"), local_now.date())
    weeks = _bounded_int(request.get("weeks", 1), "$.weeks", 1, 4)
    weekdays = _weekdays(request.get("weekdays", [1, 2, 3, 4, 5]))
    morning = _local_time(
        request.get("morning_departure_time", config["morning_departure_time"]),
        "$.morning_departure_time",
    )
    evening = _local_time(
        request.get("evening_departure_time", config["evening_departure_time"]),
        "$.evening_departure_time",
    )
    modes = _travel_modes(
        request.get("travel_modes", ["TWO_WHEELER", "DRIVE"]),
        "$.travel_modes",
    )
    rate_limit_qpm = _bounded_int(
        request.get("rate_limit_qpm", 60), "$.rate_limit_qpm", 1, 3000
    )
    confirmation_threshold = _bounded_int(
        request.get("confirmation_threshold", 20),
        "$.confirmation_threshold",
        1,
        1000,
    )
    companies = list(config["companies"])
    additional = request.get("additional_companies", [])
    if not isinstance(additional, list):
        raise InputError("INVALID_INPUT", "必須是 array", "$.additional_companies")
    for index, company in enumerate(additional):
        companies.append(_validate_company(company, f"$.additional_companies[{index}]"))
    _reject_duplicate_company_ids(companies)

    selected_dates = [
        start + timedelta(days=day_index)
        for day_index in range(weeks * 7)
        if (start + timedelta(days=day_index)).isoweekday() in weekdays
    ]
    if not selected_dates:
        raise InputError("INVALID_INPUT", "沒有符合 weekdays 的取樣日期", "$.weekdays")

    samples: list[dict[str, object]] = []
    home = config["home"]
    for sample_date in selected_dates:
        for company in companies:
            for direction, departure_clock in (
                ("outbound", morning),
                ("return", evening),
            ):
                if direction == "outbound":
                    origin, destination = home, company
                else:
                    origin, destination = company, home
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
                            str(company["id"]),
                            sample_date.strftime("%Y%m%d"),
                            direction,
                            mode.lower().replace("_", "-"),
                        ]
                    )
                    samples.append(
                        {
                            "request_id": request_id,
                            "company_id": company["id"],
                            "company_name": company["name"],
                            "date": sample_date.isoformat(),
                            "direction": direction,
                            "origin_label": origin["label"],
                            "destination_label": destination["label"],
                            "origin": origin["location"],
                            "destination": destination["location"],
                            "travel_mode": mode,
                            "departure_time": departure.isoformat(),
                        }
                    )

    request_count = len(samples)
    enterprise = sum(
        1 for sample in samples if sample["travel_mode"] == "TWO_WHEELER"
    )
    pro = request_count - enterprise
    plan_without_id: dict[str, object] = {
        "schema_version": "1",
        "plan_contract_version": "1.0.0",
        "created_at": now.isoformat(),
        "dependency": dict(dependency_value),
        "schedule": {
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=weeks * 7 - 1)).isoformat(),
            "weeks": weeks,
            "weekdays": weekdays,
            "dates": [item.isoformat() for item in selected_dates],
            "utc_offset": config["utc_offset"],
            "morning_departure_time": morning.strftime("%H:%M"),
            "evening_departure_time": evening.strftime("%H:%M"),
            "travel_modes": modes,
        },
        "preview": {
            "company_count": len(companies),
            "request_count": request_count,
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
        },
        "samples": samples,
    }
    return {
        **plan_without_id,
        "plan_id": _content_id(plan_without_id),
    }


def validate_execution_plan(value: object, *, now: datetime) -> dict[str, object]:
    plan = _require_object(value, "$")
    _reject_unknown(
        plan,
        {
            "schema_version",
            "plan_contract_version",
            "created_at",
            "dependency",
            "schedule",
            "preview",
            "samples",
            "plan_id",
        },
        "$",
    )
    plan_id = _nonempty_string(plan.get("plan_id"), "$.plan_id")
    content = {key: item for key, item in plan.items() if key != "plan_id"}
    if plan_id != _content_id(content):
        raise InputError(
            "PLAN_ID_MISMATCH",
            "plan 內容已改變；請重新執行 plan，並使用新的 plan_id",
            "$.plan_id",
        )
    if plan.get("schema_version") != "1":
        raise InputError("INVALID_PLAN", "schema_version 必須是 1", "$.schema_version")
    if plan.get("plan_contract_version") != "1.0.0":
        raise InputError(
            "INVALID_PLAN",
            "plan_contract_version 必須是 1.0.0",
            "$.plan_contract_version",
        )
    samples = plan.get("samples")
    if not isinstance(samples, list) or not samples:
        raise InputError("INVALID_PLAN", "samples 必須是非空 array", "$.samples")
    preview = _require_object(plan.get("preview"), "$.preview")
    _reject_unknown(
        preview,
        {
            "company_count",
            "request_count",
            "retry_limit",
            "maximum_http_requests",
            "rate_limit_qpm",
            "local_rate_limit_only",
            "confirmation_threshold",
            "confirmation_required",
            "estimated_sku_requests",
        },
        "$.preview",
    )
    if preview.get("request_count") != len(samples):
        raise InputError(
            "INVALID_PLAN", "request_count 與 samples 數量不一致", "$.preview.request_count"
        )
    if preview.get("retry_limit") != 2:
        raise InputError("INVALID_PLAN", "retry_limit 必須是 2", "$.preview.retry_limit")
    if preview.get("maximum_http_requests") != len(samples) * 3:
        raise InputError(
            "INVALID_PLAN",
            "maximum_http_requests 必須等於 request_count 的三倍",
            "$.preview.maximum_http_requests",
        )
    threshold = preview.get("confirmation_threshold")
    if type(threshold) is not int or not 1 <= threshold <= 1000:
        raise InputError(
            "INVALID_PLAN",
            "confirmation_threshold 必須是 1 到 1000 的整數",
            "$.preview.confirmation_threshold",
        )
    if preview.get("confirmation_required") is not (len(samples) > threshold):
        raise InputError(
            "INVALID_PLAN",
            "confirmation_required 與 request_count 不一致",
            "$.preview.confirmation_required",
        )
    _bounded_int(preview.get("rate_limit_qpm"), "$.preview.rate_limit_qpm", 1, 3000)
    if preview.get("local_rate_limit_only") is not True:
        raise InputError(
            "INVALID_PLAN",
            "local_rate_limit_only 必須是 true",
            "$.preview.local_rate_limit_only",
        )

    request_ids: set[str] = set()
    mode_counts = {"DRIVE": 0, "TWO_WHEELER": 0}
    company_ids: set[str] = set()
    sample_dates: set[str] = set()
    for index, sample_value in enumerate(samples):
        sample = _require_object(sample_value, f"$.samples[{index}]")
        _reject_unknown(
            sample,
            {
                "request_id",
                "company_id",
                "company_name",
                "date",
                "direction",
                "origin_label",
                "destination_label",
                "origin",
                "destination",
                "travel_mode",
                "departure_time",
            },
            f"$.samples[{index}]",
        )
        request_id = _nonempty_string(
            sample.get("request_id"), f"$.samples[{index}].request_id"
        )
        if request_id in request_ids:
            raise InputError(
                "INVALID_PLAN",
                "request_id 不得重複",
                f"$.samples[{index}].request_id",
            )
        request_ids.add(request_id)
        company_id = _nonempty_string(
            sample.get("company_id"), f"$.samples[{index}].company_id"
        )
        company_ids.add(company_id)
        _nonempty_string(sample.get("company_name"), f"$.samples[{index}].company_name")
        _nonempty_string(sample.get("origin_label"), f"$.samples[{index}].origin_label")
        _nonempty_string(
            sample.get("destination_label"), f"$.samples[{index}].destination_label"
        )
        _validate_location(sample.get("origin"), f"$.samples[{index}].origin")
        _validate_location(sample.get("destination"), f"$.samples[{index}].destination")
        if sample.get("direction") not in {"outbound", "return"}:
            raise InputError(
                "INVALID_PLAN",
                "direction 必須是 outbound 或 return",
                f"$.samples[{index}].direction",
            )
        mode = sample.get("travel_mode")
        if mode not in mode_counts:
            raise InputError(
                "INVALID_PLAN",
                "travel_mode 必須是 DRIVE 或 TWO_WHEELER",
                f"$.samples[{index}].travel_mode",
            )
        mode_counts[str(mode)] += 1
        sample_date = _nonempty_string(
            sample.get("date"), f"$.samples[{index}].date"
        )
        try:
            parsed_sample_date = date.fromisoformat(sample_date)
        except ValueError as exc:
            raise InputError(
                "INVALID_PLAN",
                "date 必須是 YYYY-MM-DD",
                f"$.samples[{index}].date",
            ) from exc
        sample_dates.add(sample_date)
        departure_text = _nonempty_string(
            sample.get("departure_time"), f"$.samples[{index}].departure_time"
        )
        try:
            departure = datetime.fromisoformat(departure_text)
        except ValueError as exc:
            raise InputError(
                "INVALID_PLAN",
                "departure_time 必須是 ISO 8601 date-time",
                f"$.samples[{index}].departure_time",
            ) from exc
        if departure.tzinfo is None or departure.utcoffset() is None:
            raise InputError(
                "INVALID_PLAN",
                "departure_time 必須包含 UTC offset",
                f"$.samples[{index}].departure_time",
            )
        if departure <= now.astimezone(departure.tzinfo):
            raise InputError(
                "PLAN_EXPIRED",
                "plan 含有已到期的 departure_time；請重新執行 plan",
                f"$.samples[{index}].departure_time",
            )
        if departure.date() != parsed_sample_date:
            raise InputError(
                "INVALID_PLAN",
                "date 必須與 departure_time 的本地日期一致",
                f"$.samples[{index}].date",
            )

    sku = _require_object(
        preview.get("estimated_sku_requests"), "$.preview.estimated_sku_requests"
    )
    if sku != {
        "routes_compute_pro": mode_counts["DRIVE"],
        "routes_compute_enterprise": mode_counts["TWO_WHEELER"],
    }:
        raise InputError(
            "INVALID_PLAN",
            "estimated_sku_requests 與 samples 不一致",
            "$.preview.estimated_sku_requests",
        )
    if preview.get("company_count") != len(company_ids):
        raise InputError(
            "INVALID_PLAN",
            "company_count 與 samples 不一致",
            "$.preview.company_count",
        )

    schedule = _require_object(plan.get("schedule"), "$.schedule")
    _reject_unknown(
        schedule,
        {
            "start_date",
            "end_date",
            "weeks",
            "weekdays",
            "dates",
            "utc_offset",
            "morning_departure_time",
            "evening_departure_time",
            "travel_modes",
        },
        "$.schedule",
    )
    _bounded_int(schedule.get("weeks"), "$.schedule.weeks", 1, 4)
    _weekdays_at_path(schedule.get("weekdays"), "$.schedule.weekdays")
    _parse_utc_offset(schedule.get("utc_offset"), "$.schedule.utc_offset")
    _local_time(
        schedule.get("morning_departure_time"),
        "$.schedule.morning_departure_time",
    )
    _local_time(
        schedule.get("evening_departure_time"),
        "$.schedule.evening_departure_time",
    )
    schedule_modes = _travel_modes(
        schedule.get("travel_modes"), "$.schedule.travel_modes"
    )
    actual_modes = {mode for mode, count in mode_counts.items() if count}
    if set(schedule_modes) != actual_modes:
        raise InputError(
            "INVALID_PLAN",
            "travel_modes 與 samples 不一致",
            "$.schedule.travel_modes",
        )
    dates_value = schedule.get("dates")
    if (
        not isinstance(dates_value, list)
        or any(not isinstance(item, str) for item in dates_value)
        or dates_value != sorted(sample_dates)
    ):
        raise InputError(
            "INVALID_PLAN", "dates 與 samples 不一致", "$.schedule.dates"
        )
    try:
        schedule_start = date.fromisoformat(
            _nonempty_string(schedule.get("start_date"), "$.schedule.start_date")
        )
        schedule_end = date.fromisoformat(
            _nonempty_string(schedule.get("end_date"), "$.schedule.end_date")
        )
    except ValueError as exc:
        raise InputError(
            "INVALID_PLAN", "start_date 與 end_date 必須是 YYYY-MM-DD", "$.schedule"
        ) from exc
    if schedule_end != schedule_start + timedelta(days=int(schedule["weeks"]) * 7 - 1):
        raise InputError(
            "INVALID_PLAN", "end_date 與 weeks 不一致", "$.schedule.end_date"
        )
    if any(
        not schedule_start <= date.fromisoformat(item) <= schedule_end
        for item in dates_value
    ):
        raise InputError(
            "INVALID_PLAN", "dates 超出 schedule 範圍", "$.schedule.dates"
        )
    return plan


def _validate_config(value: object) -> dict[str, object]:
    config = _require_object(value, "$config")
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
        "schema_versions": ["1"],
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
            "schema_version": "1",
            "travel_modes": ["DRIVE", "TWO_WHEELER"],
            "output_profile": "summary",
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
        _write_json(stdout, {"schema_version": "1", "config": metadata})
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
                "origin": sample["origin"],
                "destination": sample["destination"],
                "travel_mode": sample["travel_mode"],
                "departure_time": sample["departure_time"],
            }
        )
    return {
        "schema_version": "1",
        "profile": "summary",
        "rate_limit_qpm": preview["rate_limit_qpm"],
        "requests": requests,
    }


def analyze_route_results(
    plan: Mapping[str, object], route_value: object, *, now: datetime
) -> dict[str, object]:
    schedule = _require_object(plan.get("schedule"), "$.schedule")
    weeks = _bounded_int(schedule.get("weeks"), "$.schedule.weeks", 1, 4)
    route = _require_object(route_value, "$route_result")
    if route.get("schema_version") != "1" or route.get("cli_contract_version") != "2.0.0":
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "google-routes result contract 不相容",
            "$route_result",
        )
    results_value = route.get("results")
    if not isinstance(results_value, list):
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "results 必須是 array",
            "$route_result.results",
        )
    result_by_id: dict[str, dict[str, object]] = {}
    for index, result_value in enumerate(results_value):
        result = _require_object(result_value, f"$route_result.results[{index}]")
        request_id = _nonempty_string(
            result.get("request_id"), f"$route_result.results[{index}].request_id"
        )
        if request_id in result_by_id:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "request_id 不得重複",
                f"$route_result.results[{index}].request_id",
            )
        result_by_id[request_id] = result

    samples_value = plan.get("samples")
    assert isinstance(samples_value, list)
    expected_ids = {str(sample["request_id"]) for sample in samples_value if isinstance(sample, dict)}
    if set(result_by_id) != expected_ids:
        raise InputError(
            "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
            "result request_id 集合與 plan 不一致",
            "$route_result.results",
        )

    normalized_samples: list[dict[str, object]] = []
    for sample_value in samples_value:
        sample = _require_object(sample_value, "$.samples[]")
        provider = result_by_id[str(sample["request_id"])]
        status = provider.get("status")
        if status not in {"success", "degraded", "error"}:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "未知 route status",
                "$route_result.results[].status",
            )
        if provider.get("travel_mode") != sample.get("travel_mode"):
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "result travel_mode 與 plan 不一致",
                "$route_result.results[].travel_mode",
            )
        attempts = provider.get("attempts")
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise InputError(
                "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                "attempts 必須是 1 到 3 的整數",
                "$route_result.results[].attempts",
            )
        normalized: dict[str, object] = {
            "request_id": sample["request_id"],
            "company_id": sample["company_id"],
            "company_name": sample["company_name"],
            "date": sample["date"],
            "direction": sample["direction"],
            "travel_mode": sample["travel_mode"],
            "status": status,
            "attempts": attempts,
        }
        if status in {"success", "degraded"}:
            duration = provider.get("duration_seconds")
            static_duration = provider.get("static_duration_seconds")
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
                raise InputError(
                    "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                    "duration_seconds 必須是非負數",
                    "$route_result.results[].duration_seconds",
                )
            if (
                not isinstance(static_duration, (int, float))
                or isinstance(static_duration, bool)
                or static_duration < 0
            ):
                raise InputError(
                    "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                    "static_duration_seconds 必須是非負數",
                    "$route_result.results[].static_duration_seconds",
                )
            warnings = provider.get("warnings")
            if not isinstance(warnings, list) or any(
                not isinstance(item, str) for item in warnings
            ):
                raise InputError(
                    "GOOGLE_ROUTES_RESULT_INCOMPATIBLE",
                    "warnings 必須是 string array",
                    "$route_result.results[].warnings",
                )
            fallback = provider.get("fallback")
            if fallback is not None:
                fallback_value = _require_object(
                    fallback, "$route_result.results[].fallback"
                )
                _reject_unknown(
                    fallback_value,
                    {"routing_mode", "reason"},
                    "$route_result.results[].fallback",
                )
                fallback = {
                    "routing_mode": _nonempty_string(
                        fallback_value.get("routing_mode"),
                        "$route_result.results[].fallback.routing_mode",
                    ),
                    "reason": _nonempty_string(
                        fallback_value.get("reason"),
                        "$route_result.results[].fallback.reason",
                    ),
                }
            normalized.update(
                {
                    "duration_seconds": duration,
                    "static_duration_seconds": static_duration,
                    "warnings": warnings,
                    "fallback": fallback,
                }
            )
        else:
            provider_error = provider.get("error")
            if not isinstance(provider_error, dict):
                provider_error = {}
            safe_error: dict[str, object] = {
                "code": provider_error.get("code")
                if isinstance(provider_error.get("code"), str)
                else "UNKNOWN",
                "retryable": provider_error.get("retryable") is True,
            }
            http_status = provider_error.get("http_status")
            if type(http_status) is int and 300 <= http_status <= 599:
                safe_error["http_status"] = http_status
            normalized["error"] = safe_error
        normalized_samples.append(normalized)

    companies: list[dict[str, object]] = []
    company_order: list[tuple[str, str]] = []
    for sample in normalized_samples:
        identity = (str(sample["company_id"]), str(sample["company_name"]))
        if identity not in company_order:
            company_order.append(identity)
    for company_id, company_name in company_order:
        company_samples = [item for item in normalized_samples if item["company_id"] == company_id]
        modes: dict[str, object] = {}
        for mode in ("TWO_WHEELER", "DRIVE"):
            mode_samples = [item for item in company_samples if item["travel_mode"] == mode]
            if not mode_samples:
                continue
            successes = [item for item in mode_samples if item["status"] == "success"]
            outbound = [float(item["duration_seconds"]) for item in successes if item["direction"] == "outbound"]
            returns = [float(item["duration_seconds"]) for item in successes if item["direction"] == "return"]
            by_date: dict[str, dict[str, float]] = {}
            for item in successes:
                by_date.setdefault(str(item["date"]), {})[str(item["direction"])] = float(item["duration_seconds"])
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
                "weekly_total_seconds": _clean_number(weekly_total) if complete else None,
                "four_week_month_estimate_seconds": _clean_number(weekly_total * 4) if complete else None,
                "samples": mode_samples,
            }
        motorcycle = modes.get("TWO_WHEELER")
        eligible = isinstance(motorcycle, dict) and motorcycle["complete"] is True
        reasons: list[str] = [] if eligible else ["機車必要樣本不完整"]
        companies.append(
            {
                "company_id": company_id,
                "company_name": company_name,
                "ranking_eligible": eligible,
                "ranking_exclusion_reasons": reasons,
                "modes": modes,
            }
        )

    ranked = [company for company in companies if company["ranking_eligible"]]
    ranked.sort(
        key=lambda company: company["modes"]["TWO_WHEELER"]["statistics"]["daily_round_trip"]["average_seconds"]
    )
    ranking = [
        {
            "rank": index,
            "company_id": company["company_id"],
            "company_name": company["company_name"],
            "daily_round_trip_average_seconds": company["modes"]["TWO_WHEELER"]["statistics"]["daily_round_trip"]["average_seconds"],
        }
        for index, company in enumerate(ranked, start=1)
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
    attempts = sum(
        int(item["attempts"])
        for item in normalized_samples
        if isinstance(item.get("attempts"), int)
    )
    return {
        "schema_version": "1",
        "analysis_contract_version": "1.0.0",
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
        "companies": companies,
        "ranking": ranking,
    }


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
            "schema_version": "1",
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
                f"{item['rank']}. {item['company_name']}："
                f"每日來回平均 {_format_seconds(item['daily_round_trip_average_seconds'])}"
            )
        lines.append("")
    lines.extend(["## 公司結果", ""])
    for company in analysis.get("companies", []):
        lines.extend([f"### {company['company_name']}", ""])
        if not company["ranking_eligible"]:
            lines.append("- 排名：不納入（機車必要樣本不完整）")
        for mode, mode_result in company["modes"].items():
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
