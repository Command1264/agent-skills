"""Validate the portable, public structure of this Agent Skill repository."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
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
