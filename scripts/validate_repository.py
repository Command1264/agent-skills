"""Validate the portable, public structure of this Agent Skill repository."""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote


AGENTS_MAX_BYTES = 24 * 1024
REQUIRED_FILES = (
    "AGENTS.md",
    "CONTEXT.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "docs/agents/domain.md",
    "docs/agents/issue-tracker.md",
    "docs/agents/release.md",
    "docs/agents/security-and-privacy.md",
    "docs/agents/skill-authoring.md",
    "docs/agents/testing.md",
    "docs/agents/triage-labels.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/new-skill.yml",
    ".github/ISSUE_TEMPLATE/enhancement.yml",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/docs-maintenance.yml",
    ".github/workflows/ci.yml",
)
TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".toml"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SECRET_PATTERNS = (
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("GitHub token", re.compile(r"gh[oprsu]_[0-9A-Za-z]{20,}")),
)
KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SchemaExamplePair = tuple[str, str]
SCHEMA_EXAMPLE_PAIRS: tuple[SchemaExamplePair, ...] = (
    (
        "skills/google-routes/schemas/query-v1.schema.json",
        "skills/google-routes/examples/query.json",
    ),
    (
        "skills/google-routes/schemas/result-v1.schema.json",
        "skills/google-routes/examples/result.json",
    ),
    (
        "skills/google-routes/schemas/query-v2.schema.json",
        "skills/google-routes/examples/itinerary-query.json",
    ),
    (
        "skills/google-routes/schemas/result-v2.schema.json",
        "skills/google-routes/examples/itinerary-result.json",
    ),
    (
        "skills/commute-analyzer/schemas/config-v1.schema.json",
        "skills/commute-analyzer/examples/config.json",
    ),
    (
        "skills/commute-analyzer/schemas/plan-request-v1.schema.json",
        "skills/commute-analyzer/examples/plan-request.json",
    ),
    (
        "skills/commute-analyzer/schemas/plan-v1.schema.json",
        "skills/commute-analyzer/examples/plan.json",
    ),
    (
        "skills/commute-analyzer/schemas/result-v1.schema.json",
        "skills/commute-analyzer/examples/result.json",
    ),
    (
        "skills/commute-analyzer/schemas/config-v2.schema.json",
        "skills/commute-analyzer/examples/config-v2.json",
    ),
    (
        "skills/commute-analyzer/schemas/plan-request-v2.schema.json",
        "skills/commute-analyzer/examples/plan-request-v2.json",
    ),
    (
        "skills/commute-analyzer/schemas/plan-v2.schema.json",
        "skills/commute-analyzer/examples/plan-v2.json",
    ),
    (
        "skills/commute-analyzer/schemas/result-v2.schema.json",
        "skills/commute-analyzer/examples/result-v2.json",
    ),
)


def read_utf8(path: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"無法以 UTF-8 讀取 {path}: {exc}")
        return None


def validate_required_files(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少必要檔案: {relative}")
        elif path.stat().st_size == 0:
            errors.append(f"必要檔案是空的: {relative}")
    agents = root / "AGENTS.md"
    if agents.is_file() and agents.stat().st_size > AGENTS_MAX_BYTES:
        errors.append(
            f"AGENTS.md 為 {agents.stat().st_size} bytes，超過 {AGENTS_MAX_BYTES} bytes"
        )
    return errors


def validate_markdown_links(root: Path) -> list[str]:
    errors: list[str] = []
    for markdown in sorted(root.rglob("*.md")):
        if ".git" in markdown.parts:
            continue
        text = read_utf8(markdown, errors)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                raw_target = match.group(1).strip().strip("<>")
                if not raw_target or raw_target.startswith("#"):
                    continue
                if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_target):
                    continue
                target_without_fragment = raw_target.split("#", 1)[0]
                target = markdown.parent / unquote(target_without_fragment)
                if not target.exists():
                    relative_markdown = markdown.relative_to(root)
                    errors.append(
                        f"失效的 Markdown link: {relative_markdown}:{line_number} -> {raw_target}"
                    )
    return errors


def parse_frontmatter(text: str) -> dict[str, str] | None:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None
    closing = normalized.find("\n---\n", 4)
    if closing == -1:
        return None
    fields: dict[str, str] = {}
    for line in normalized[4:closing].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def validate_skills(root: Path) -> list[str]:
    errors: list[str] = []
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return ["缺少 skills/ 目錄"]
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        if not KEBAB_CASE.fullmatch(skill_dir.name):
            errors.append(f"Skill 目錄不是 kebab-case: {skill_dir.relative_to(root)}")
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"Skill 目錄缺少 SKILL.md: {skill_dir.relative_to(root)}")
            continue
        text = read_utf8(skill_file, errors)
        if text is None:
            continue
        frontmatter = parse_frontmatter(text)
        if frontmatter is None:
            errors.append(f"SKILL.md 缺少有效 YAML frontmatter: {skill_file.relative_to(root)}")
            continue
        if frontmatter.get("name") != skill_dir.name:
            errors.append(
                f"Skill name 必須等於目錄名稱: {skill_file.relative_to(root)}"
            )
        if not frontmatter.get("description"):
            errors.append(f"Skill description 不得為空: {skill_file.relative_to(root)}")
    return errors


def validate_json(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.json")):
        if ".git" in path.parts:
            continue
        text = read_utf8(path, errors)
        if text is None:
            continue
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"無效 JSON: {path.relative_to(root)}:{exc.lineno}:{exc.colno}")
    return errors


def _json_pointer(document: Any, fragment: str) -> Any:
    current = document
    if fragment in ("", "#"):
        return current
    if not fragment.startswith("#/"):
        raise ValueError(f"不支援的 JSON pointer: {fragment}")
    for raw_part in fragment[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"找不到 JSON pointer: {fragment}")
        current = current[part]
    return current


def _load_schema_reference(schema_path: Path, reference: str) -> tuple[Any, Path]:
    target_text, separator, fragment_text = reference.partition("#")
    target_path = schema_path if not target_text else schema_path.parent / target_text
    document = json.loads(target_path.read_text(encoding="utf-8"))
    fragment = f"#{fragment_text}" if separator else ""
    return _json_pointer(document, fragment), target_path


def _matches_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return expected in checks and checks[expected](value)


def _validate_schema_value(
    value: Any,
    schema: Any,
    *,
    schema_path: Path,
    value_path: str,
) -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{value_path}: schema 不允許此值"]
    if not isinstance(schema, dict):
        return [f"{value_path}: schema 必須是 object 或 boolean"]

    if "$ref" in schema:
        try:
            referenced, referenced_path = _load_schema_reference(
                schema_path, str(schema["$ref"])
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return [f"{value_path}: 無法解析 $ref {schema['$ref']}: {exc}"]
        return _validate_schema_value(
            value,
            referenced,
            schema_path=referenced_path,
            value_path=value_path,
        )

    errors: list[str] = []
    for branch in schema.get("allOf", []):
        errors.extend(
            _validate_schema_value(
                value, branch, schema_path=schema_path, value_path=value_path
            )
        )
    if "oneOf" in schema:
        branch_results = [
            _validate_schema_value(
                value, branch, schema_path=schema_path, value_path=value_path
            )
            for branch in schema["oneOf"]
        ]
        matching_branches = sum(not result for result in branch_results)
        if matching_branches != 1:
            errors.append(f"{value_path}: 必須只符合 oneOf 的一個分支")
            if matching_branches == 0:
                for branch_error in dict.fromkeys(
                    error
                    for branch_result in branch_results
                    for error in branch_result
                ):
                    errors.append(branch_error)
            return errors

    expected_types = schema.get("type")
    if expected_types is not None:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(_matches_type(value, item) for item in expected_types):
            errors.append(f"{value_path}: 型別不符合 {expected_types}")
            return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{value_path}: 必須等於 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{value_path}: 不在允許的 enum 中")

    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{value_path}: object 欄位不足")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{value_path}: object 欄位過多")
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{value_path}.{required}: 缺少必要欄位")
        for key, item in value.items():
            child_path = f"{value_path}.{key}"
            if key in properties:
                errors.extend(
                    _validate_schema_value(
                        item,
                        properties[key],
                        schema_path=schema_path,
                        value_path=child_path,
                    )
                )
            elif schema.get("additionalProperties") is False:
                errors.append(f"{child_path}: 未知欄位")
            elif isinstance(schema.get("additionalProperties"), (dict, bool)):
                errors.extend(
                    _validate_schema_value(
                        item,
                        schema["additionalProperties"],
                        schema_path=schema_path,
                        value_path=child_path,
                    )
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{value_path}: array 項目不足")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{value_path}: array 項目過多")
        if schema.get("uniqueItems"):
            serialized = [
                json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value
            ]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{value_path}: array 項目不得重複")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(
                    _validate_schema_value(
                        item,
                        schema["items"],
                        schema_path=schema_path,
                        value_path=f"{value_path}[{index}]",
                    )
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{value_path}: 字串過短")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{value_path}: 字串過長")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{value_path}: 不符合 pattern")
        if schema.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{value_path}: 不是有效 date")
        elif schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{value_path}: 不是有效 date-time")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{value_path}: 小於 minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{value_path}: 大於 maximum")

    return errors


def validate_json_schema_examples(
    root: Path, pairs: Sequence[SchemaExamplePair]
) -> list[str]:
    errors: list[str] = []
    for schema_relative, example_relative in pairs:
        schema_path = root / schema_relative
        example_path = root / example_relative
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            example = json.loads(example_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"無法讀取 schema/example {schema_relative}: {exc}")
            continue
        validation_errors = _validate_schema_value(
            example, schema, schema_path=schema_path, value_path="$"
        )
        errors.extend(
            f"Schema example 不相容: {example_relative}: {message}"
            for message in validation_errors
        )
    return errors


def validate_no_secrets(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = read_utf8(path, errors)
        if text is None:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"疑似 {label}: {path.relative_to(root)}")
    return errors


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_required_files(root))
    errors.extend(validate_markdown_links(root))
    errors.extend(validate_skills(root))
    errors.extend(validate_json(root))
    errors.extend(validate_json_schema_examples(root, SCHEMA_EXAMPLE_PAIRS))
    errors.extend(validate_no_secrets(root))
    return errors


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    errors = validate_repository(root)
    if errors:
        print("Repository 驗證失敗：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Repository 驗證通過。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
