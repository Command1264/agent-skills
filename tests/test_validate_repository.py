from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_repository import (
    parse_frontmatter,
    validate_markdown_links,
    validate_no_secrets,
    validate_skills,
)


class FrontmatterTests(unittest.TestCase):
    def test_parses_required_fields(self) -> None:
        fields = parse_frontmatter(
            "---\nname: example-skill\ndescription: 範例說明\n---\n# Skill\n"
        )

        self.assertEqual(
            fields,
            {"name": "example-skill", "description": "範例說明"},
        )

    def test_rejects_missing_closing_delimiter(self) -> None:
        self.assertIsNone(parse_frontmatter("---\nname: example-skill\n"))


class MarkdownLinkTests(unittest.TestCase):
    def test_reports_missing_local_target_but_ignores_https(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text(
                "[missing](docs/missing.md) [web](https://example.com)\n",
                encoding="utf-8",
            )

            errors = validate_markdown_links(root)

        self.assertEqual(len(errors), 1)
        self.assertIn("docs/missing.md", errors[0])


class SkillValidationTests(unittest.TestCase):
    def test_accepts_matching_skill_name_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill = root / "skills" / "example-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: example-skill\ndescription: 範例說明\n---\n# Skill\n",
                encoding="utf-8",
            )

            errors = validate_skills(root)

        self.assertEqual(errors, [])

    def test_rejects_mismatched_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill = root / "skills" / "example-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: another-skill\ndescription: 範例說明\n---\n# Skill\n",
                encoding="utf-8",
            )

            errors = validate_skills(root)

        self.assertEqual(len(errors), 1)
        self.assertIn("Skill name", errors[0])


class SecretValidationTests(unittest.TestCase):
    def test_reports_google_api_key_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example.md").write_text(
                "AIza" + "A" * 35,
                encoding="utf-8",
            )

            errors = validate_no_secrets(root)

        self.assertEqual(len(errors), 1)
        self.assertIn("Google API key", errors[0])


if __name__ == "__main__":
    unittest.main()
