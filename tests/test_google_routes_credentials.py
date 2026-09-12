from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "skills"
    / "google-routes"
    / "scripts"
    / "google_routes_credentials.py"
)
SPEC = importlib.util.spec_from_file_location("google_routes_credentials", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
credentials = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(credentials)


TEST_KEY = "test-only-key-material"


class CredentialPathTests(unittest.TestCase):
    def test_windows_path_avoids_packaged_python_appdata_virtualization(self) -> None:
        home = Path("example-user-home")
        path = credentials.default_credentials_path(
            platform_name="win32",
            environ={"LOCALAPPDATA": r"C:\Users\example\AppData\Local"},
            home=home,
        )

        self.assertEqual(
            path,
            home
            / ".config"
            / "command1264-skills"
            / "credentials"
            / "google-routes.toml",
        )
        self.assertNotIn("AppData", str(path))

    def test_macos_and_linux_use_standard_user_config_locations(self) -> None:
        home = Path("/users/example")

        self.assertEqual(
            credentials.default_credentials_path(
                platform_name="darwin", environ={}, home=home
            ),
            home
            / "Library"
            / "Application Support"
            / "command1264-skills"
            / "credentials"
            / "google-routes.toml",
        )
        self.assertEqual(
            credentials.default_credentials_path(
                platform_name="linux",
                environ={"XDG_CONFIG_HOME": "/custom/config"},
                home=home,
            ),
            Path("/custom/config/command1264-skills/credentials/google-routes.toml"),
        )

    def test_linux_ignores_empty_or_relative_xdg_config_home(self) -> None:
        home = Path("/users/example")
        expected = home / ".config/command1264-skills/credentials/google-routes.toml"

        for configured in ("", "relative/config", "   "):
            with self.subTest(configured=configured):
                self.assertEqual(
                    credentials.default_credentials_path(
                        platform_name="linux",
                        environ={"XDG_CONFIG_HOME": configured},
                        home=home,
                    ),
                    expected,
                )


class CredentialReadTests(unittest.TestCase):
    def _write(self, root: Path, text: str) -> Path:
        path = root / "google-routes.toml"
        path.write_text(text, encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def test_loads_strict_toml_without_exposing_key_in_representation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                f'schema_version = "1"\napi_key = "{TEST_KEY}"\n',
            )

            result = credentials.load_credentials(path=path, environ={})

        self.assertEqual(result.api_key, TEST_KEY)
        self.assertNotIn(TEST_KEY, repr(result))

    def test_legacy_environment_variable_fails_before_file_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                f'schema_version = "1"\napi_key = "{TEST_KEY}"\n',
            )

            with self.assertRaises(credentials.CredentialError) as context:
                credentials.load_credentials(
                    path=path,
                    environ={"GOOGLE_MAPS_API_KEY": "legacy-secret"},
                )

        self.assertEqual(
            context.exception.code, "legacy_api_key_environment_variable"
        )
        self.assertNotIn("legacy-secret", str(context.exception))
        self.assertNotIn(TEST_KEY, str(context.exception))

    def test_unknown_fields_and_placeholders_fail_closed_without_leaking(self) -> None:
        cases = (
            (
                'schema_version = "1"\napi_key = "secret-value"\nextra = true\n',
                "credential_file_invalid",
            ),
            (
                'schema_version = "1"\napi_key = "<Google Maps Platform API key>"\n',
                "credential_file_invalid",
            ),
        )
        for text, expected_code in cases:
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as directory:
                    path = self._write(Path(directory), text)
                    with self.assertRaises(credentials.CredentialError) as context:
                        credentials.load_credentials(path=path, environ={})
                self.assertEqual(context.exception.code, expected_code)
                self.assertNotIn("secret-value", str(context.exception))

    def test_oversized_file_fails_before_toml_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(Path(directory), "x" * 8193)
            with self.assertRaises(credentials.CredentialError) as context:
                credentials.load_credentials(path=path, environ={})

        self.assertEqual(context.exception.code, "credential_file_too_large")

    def test_directory_and_invalid_toml_fail_with_stable_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(credentials.CredentialError) as directory_error:
                credentials.load_credentials(path=root, environ={})
            invalid_path = self._write(root, "not valid toml = [")
            with self.assertRaises(credentials.CredentialError) as invalid_error:
                credentials.load_credentials(path=invalid_path, environ={})

        self.assertEqual(
            directory_error.exception.code, "credential_file_not_regular"
        )
        self.assertEqual(invalid_error.exception.code, "credential_file_invalid")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not authoritative on Windows")
    def test_posix_group_or_other_access_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                f'schema_version = "1"\napi_key = "{TEST_KEY}"\n',
            )
            path.chmod(0o644)

            with self.assertRaises(credentials.CredentialError) as context:
                credentials.load_credentials(path=path, environ={})

        self.assertEqual(
            context.exception.code, "credential_file_permissions_unsafe"
        )


class CredentialWriteTests(unittest.TestCase):
    def test_atomic_writer_creates_private_file_and_can_replace_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "google-routes.toml"

            credentials.write_credentials(
                path=path,
                api_key_reader=lambda _: TEST_KEY,
            )
            credentials.write_credentials(
                path=path,
                api_key_reader=lambda _: "replacement-test-key",
            )
            loaded = credentials.load_credentials(path=path, environ={})

            self.assertEqual(loaded.api_key, "replacement-test-key")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_writer_rejects_placeholder_without_creating_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google-routes.toml"

            with self.assertRaises(credentials.CredentialError) as context:
                credentials.write_credentials(
                    path=path,
                    api_key_reader=lambda _: "<Google Maps Platform API key>",
                )

            self.assertEqual(context.exception.code, "credential_file_invalid")
            self.assertFalse(path.exists())

    def test_failed_atomic_replace_preserves_existing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google-routes.toml"
            credentials.write_credentials(
                path=path,
                api_key_reader=lambda _: TEST_KEY,
            )

            def fail_replace(source: Path, target: Path) -> None:
                del source, target
                raise OSError("private operating system detail")

            with self.assertRaises(credentials.CredentialError) as context:
                credentials.write_credentials(
                    path=path,
                    api_key_reader=lambda _: "replacement-test-key",
                    replace=fail_replace,
                )

            loaded = credentials.load_credentials(path=path, environ={})
            self.assertEqual(loaded.api_key, TEST_KEY)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            self.assertNotIn("private operating system detail", str(context.exception))


if __name__ == "__main__":
    unittest.main()
