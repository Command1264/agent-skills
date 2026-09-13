from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import scripts.validate_repository as repository_validator
from scripts.validate_repository import (
    parse_frontmatter,
    validate_markdown_links,
    validate_no_secrets,
    validate_skills,
)


ROOT = Path(__file__).resolve().parents[1]


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


class JsonSchemaExampleTests(unittest.TestCase):
    def _validate_commute_example(
        self, schema_name: str, example: object
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = root / "schemas"
            examples = root / "examples"
            schemas.mkdir()
            examples.mkdir()
            source = ROOT / "skills" / "commute-analyzer" / "schemas"
            shutil.copy2(source / schema_name, schemas / schema_name)
            if schema_name != "config-v2.schema.json":
                shutil.copy2(
                    source / "config-v2.schema.json",
                    schemas / "config-v2.schema.json",
                )
            (examples / "example.json").write_text(
                json.dumps(example, ensure_ascii=False),
                encoding="utf-8",
            )
            return repository_validator.validate_json_schema_examples(
                root,
                ((f"schemas/{schema_name}", "examples/example.json"),),
            )

    def test_pattern_uses_json_schema_search_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = root / "schemas"
            examples = root / "examples"
            schemas.mkdir()
            examples.mkdir()
            (schemas / "version.schema.json").write_text(
                json.dumps({"type": "string", "pattern": "^2\\."}),
                encoding="utf-8",
            )
            (examples / "version.json").write_text('"2.1.0"', encoding="utf-8")

            errors = repository_validator.validate_json_schema_examples(
                root,
                (("schemas/version.schema.json", "examples/version.json"),),
            )

        self.assertEqual(errors, [])

    def test_rejects_object_below_minimum_property_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = root / "schemas"
            examples = root / "examples"
            schemas.mkdir()
            examples.mkdir()
            (schemas / "object.schema.json").write_text(
                json.dumps({"type": "object", "minProperties": 1}),
                encoding="utf-8",
            )
            (examples / "object.json").write_text("{}", encoding="utf-8")

            errors = repository_validator.validate_json_schema_examples(
                root,
                (("schemas/object.schema.json", "examples/object.json"),),
            )

        self.assertEqual(len(errors), 1)
        self.assertIn("$", errors[0])

    def test_validates_examples_through_local_refs_and_strict_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            schemas = root / "schemas"
            examples = root / "examples"
            schemas.mkdir()
            examples.mkdir()
            (schemas / "shared.schema.json").write_text(
                json.dumps(
                    {
                        "$defs": {
                            "item": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["id"],
                                "properties": {"id": {"type": "string"}},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (schemas / "example.schema.json").write_text(
                json.dumps(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["item"],
                        "properties": {
                            "item": {"$ref": "shared.schema.json#/$defs/item"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            valid = examples / "valid.json"
            invalid = examples / "invalid.json"
            valid.write_text('{"item":{"id":"ok"}}', encoding="utf-8")
            invalid.write_text(
                '{"item":{"id":"bad","unexpected":true}}', encoding="utf-8"
            )

            valid_errors = repository_validator.validate_json_schema_examples(
                root,
                (("schemas/example.schema.json", "examples/valid.json"),),
            )
            invalid_errors = repository_validator.validate_json_schema_examples(
                root,
                (("schemas/example.schema.json", "examples/invalid.json"),),
            )

        self.assertEqual(valid_errors, [])
        self.assertEqual(len(invalid_errors), 1)
        self.assertIn("$.item.unexpected", invalid_errors[0])

    def test_repository_examples_match_their_declared_schemas(self) -> None:
        errors = repository_validator.validate_json_schema_examples(
            ROOT, repository_validator.SCHEMA_EXAMPLE_PAIRS
        )

        self.assertEqual(errors, [])

    def test_config_v2_rejects_ambiguous_location_and_unknown_fields(self) -> None:
        config = json.loads(
            (ROOT / "skills/commute-analyzer/examples/config-v2.json").read_text(
                encoding="utf-8"
            )
        )
        config["unexpected"] = True
        config["locations"][0]["location"]["place_id"] = "ChIJAlsoPresent"

        errors = self._validate_commute_example("config-v2.schema.json", config)

        self.assertTrue(any("$.unexpected" in error for error in errors))
        self.assertTrue(
            any("$.locations[0].location" in error for error in errors)
        )

    def test_plan_request_v2_rejects_more_than_twelve_points(self) -> None:
        request = json.loads(
            (
                ROOT
                / "skills/commute-analyzer/examples/plan-request-v2.json"
            ).read_text(encoding="utf-8")
        )
        request["journeys"][0]["outbound"]["points"] = [
            {"location_id": "home"} for _ in range(13)
        ]

        errors = self._validate_commute_example(
            "plan-request-v2.schema.json", request
        )

        self.assertTrue(
            any("$.journeys[0].outbound.points" in error for error in errors)
        )

    def test_plan_request_v2_rejects_ambiguous_return_definition(self) -> None:
        request = json.loads(
            (
                ROOT
                / "skills/commute-analyzer/examples/plan-request-v2.json"
            ).read_text(encoding="utf-8")
        )
        request["journeys"][0]["return"]["points"] = [
            {"location_id": "home"},
            {"location_id": "school"},
        ]

        errors = self._validate_commute_example(
            "plan-request-v2.schema.json", request
        )

        self.assertTrue(any("$.journeys[0].return" in error for error in errors))

    def test_result_v2_rejects_location_content(self) -> None:
        result = json.loads(
            (ROOT / "skills/commute-analyzer/examples/result-v2.json").read_text(
                encoding="utf-8"
            )
        )
        result["journeys"][0]["modes"]["TWO_WHEELER"]["samples"][0][
            "location"
        ] = {"address": "不應出現在結果"}

        errors = self._validate_commute_example("result-v2.schema.json", result)

        self.assertTrue(
            any(
                "$.journeys[0].modes.TWO_WHEELER.samples[0].location" in error
                for error in errors
            )
        )

    def test_plan_v2_example_has_reproducible_content_hash(self) -> None:
        plan = json.loads(
            (ROOT / "skills/commute-analyzer/examples/plan-v2.json").read_text(
                encoding="utf-8"
            )
        )
        plan_id = plan.pop("plan_id")
        canonical = json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(
            plan_id,
            "sha256:" + hashlib.sha256(canonical).hexdigest(),
        )

    def test_plan_v2_example_has_consistent_request_and_leg_counts(self) -> None:
        plan = json.loads(
            (ROOT / "skills/commute-analyzer/examples/plan-v2.json").read_text(
                encoding="utf-8"
            )
        )
        preview = plan["preview"]
        samples = plan["samples"]

        self.assertEqual(preview["request_count"], len(samples))
        self.assertEqual(
            preview["planned_leg_count"],
            sum(sample["expected_leg_count"] for sample in samples),
        )
        self.assertEqual(
            preview["maximum_http_requests"],
            len(samples) * (preview["retry_limit"] + 1),
        )
        self.assertEqual(
            preview["estimated_sku_requests"],
            {
                "routes_compute_pro": 0,
                "routes_compute_enterprise": len(samples),
            },
        )

    def test_result_v2_example_contains_no_location_fields(self) -> None:
        result = json.loads(
            (ROOT / "skills/commute-analyzer/examples/result-v2.json").read_text(
                encoding="utf-8"
            )
        )

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(
                    *(collect_keys(item) for item in value.values())
                )
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value))
            return set()

        self.assertTrue(
            {"location", "address", "place_id", "points"}.isdisjoint(
                collect_keys(result)
            )
        )

    def test_result_v2_example_leg_totals_and_ranking_are_consistent(self) -> None:
        result = json.loads(
            (ROOT / "skills/commute-analyzer/examples/result-v2.json").read_text(
                encoding="utf-8"
            )
        )
        daily_averages: dict[str, float] = {}
        for journey in result["journeys"]:
            mode = journey["modes"]["TWO_WHEELER"]
            for sample in mode["samples"]:
                self.assertEqual(
                    sample["distance_meters"],
                    sum(leg["distance_meters"] for leg in sample["legs"]),
                )
                self.assertEqual(
                    sample["duration_seconds"],
                    sum(leg["duration_seconds"] for leg in sample["legs"]),
                )
                self.assertEqual(
                    sample["static_duration_seconds"],
                    sum(
                        leg["static_duration_seconds"] for leg in sample["legs"]
                    ),
                )
            daily_averages[journey["journey_id"]] = mode["statistics"][
                "daily_round_trip"
            ]["average_seconds"]

        self.assertEqual(
            [entry["journey_id"] for entry in result["ranking"]],
            sorted(daily_averages, key=daily_averages.get),
        )


if __name__ == "__main__":
    unittest.main()
