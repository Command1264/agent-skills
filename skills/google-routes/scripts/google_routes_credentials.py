#!/usr/bin/env python3
"""Provider-owned credential storage for google-routes."""

from __future__ import annotations

import getpass
import json
import os
import stat
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping


CREDENTIAL_SCHEMA_VERSION = "1"
MAX_CREDENTIAL_FILE_BYTES = 8 * 1024
LEGACY_ENVIRONMENT_VARIABLE = "GOOGLE_MAPS_API_KEY"
_EXPECTED_FIELDS = {"schema_version", "api_key"}
_PLACEHOLDERS = {
    "<google maps platform api key>",
    "<api key>",
    "your-api-key",
    "replace-me",
    "changeme",
}


class CredentialError(ValueError):
    """A credential failure whose message never contains credential material."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}（{path}）：{message}")
        self.code = code
        self.path = path
        self.message = message


class GoogleRoutesCredentials:
    """Resolved credential material with a deliberately redacted representation."""

    __slots__ = ("api_key", "path", "schema_version")

    def __init__(self, *, api_key: str, path: Path, schema_version: str) -> None:
        self.api_key = api_key
        self.path = path
        self.schema_version = schema_version

    def __repr__(self) -> str:
        return (
            "GoogleRoutesCredentials("
            f"path={self.path!r}, schema_version={self.schema_version!r}, "
            "api_key=<redacted>)"
        )


def default_credentials_path(
    *, platform_name: str, environ: Mapping[str, str], home: Path
) -> Path:
    """Return one deterministic user-level path without credential path overrides."""
    if platform_name == "win32":
        # Microsoft Store Python virtualizes AppData per package. A home-level
        # dot-config path stays visible to packaged and unpackaged runtimes.
        config_base = home / ".config"
    elif platform_name == "darwin":
        config_base = home / "Library" / "Application Support"
    else:
        configured_base = environ.get("XDG_CONFIG_HOME", "").strip()
        candidate = Path(configured_base) if configured_base else None
        config_base = (
            candidate
            if candidate is not None and PurePosixPath(configured_base).is_absolute()
            else home / ".config"
        )
    return (
        config_base
        / "command1264-skills"
        / "credentials"
        / "google-routes.toml"
    )


def legacy_environment_variable_is_set(environ: Mapping[str, str]) -> bool:
    value = environ.get(LEGACY_ENVIRONMENT_VARIABLE, "")
    return bool(value.strip())


def load_credentials(
    *,
    path: Path,
    environ: Mapping[str, str],
    reject_legacy_environment: bool = True,
) -> GoogleRoutesCredentials:
    """Read and validate a strict TOML credential file."""
    if reject_legacy_environment and legacy_environment_variable_is_set(environ):
        raise CredentialError(
            "legacy_api_key_environment_variable",
            "$environment.GOOGLE_MAPS_API_KEY",
            "請移除舊環境變數；google-routes v2 只使用 secret file",
        )
    raw = _read_regular_private_file(path)
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file",
            "檔案必須是 UTF-8 TOML 且符合 credential schema v1",
        ) from error
    if set(value) != _EXPECTED_FIELDS:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file",
            "只能包含 schema_version 與 api_key",
        )
    if value.get("schema_version") != CREDENTIAL_SCHEMA_VERSION:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file.schema_version",
            "schema_version 必須是 1",
        )
    api_key = _validate_api_key(value.get("api_key"))
    return GoogleRoutesCredentials(
        api_key=api_key,
        path=path,
        schema_version=CREDENTIAL_SCHEMA_VERSION,
    )


def write_credentials(
    *,
    path: Path,
    api_key_reader: Callable[[str], str] = getpass.getpass,
    replace: Callable[[Path, Path], object] = os.replace,
) -> GoogleRoutesCredentials:
    """Interactively replace the credential file without exposing the key in argv."""
    try:
        api_key = _validate_api_key(api_key_reader("Google Maps Platform API key: "))
    except (EOFError, KeyboardInterrupt, OSError) as error:
        raise CredentialError(
            "credential_update_failed",
            "$credential_file",
            "未取得 API key，既有 credential 未變更",
        ) from error

    parent = path.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise CredentialError(
            "credential_update_failed",
            "$credential_file",
            "無法建立 credential 目錄",
        ) from error

    content = (
        f'schema_version = "{CREDENTIAL_SCHEMA_VERSION}"\n'
        f"api_key = {json.dumps(api_key, ensure_ascii=True)}\n"
    ).encode("utf-8")
    if len(content) > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialError(
            "credential_file_too_large",
            "$credential_file.api_key",
            f"credential file 不得超過 {MAX_CREDENTIAL_FILE_BYTES} bytes",
        )
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=".google-routes-",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            os.chmod(temporary_path, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        replace(temporary_path, path)
        temporary_path = None
        if os.name != "nt":
            path.chmod(0o600)
    except OSError as error:
        raise CredentialError(
            "credential_update_failed",
            "$credential_file",
            "無法安全更新 credential；既有檔案未被刻意覆寫",
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return GoogleRoutesCredentials(
        api_key=api_key,
        path=path,
        schema_version=CREDENTIAL_SCHEMA_VERSION,
    )


def _read_regular_private_file(path: Path) -> bytes:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError as error:
        raise CredentialError(
            "credential_file_not_found",
            "$credential_file",
            "找不到 google-routes secret file；請執行 credentials set",
        ) from error
    except OSError as error:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file",
            "credential file 無法檢查",
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise CredentialError(
            "credential_file_not_regular",
            "$credential_file",
            "credential 路徑必須是一般檔案且不得是 symbolic link",
        )
    if metadata.st_size > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialError(
            "credential_file_too_large",
            "$credential_file",
            f"credential file 不得超過 {MAX_CREDENTIAL_FILE_BYTES} bytes",
        )
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise CredentialError(
            "credential_file_permissions_unsafe",
            "$credential_file",
            "credential file 僅能由目前使用者讀寫；請設定為 0600",
        )
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_CREDENTIAL_FILE_BYTES + 1)
    except OSError as error:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file",
            "credential file 無法讀取",
        ) from error
    if len(raw) > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialError(
            "credential_file_too_large",
            "$credential_file",
            f"credential file 不得超過 {MAX_CREDENTIAL_FILE_BYTES} bytes",
        )
    return raw


def _validate_api_key(value: object) -> str:
    if not isinstance(value, str):
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file.api_key",
            "api_key 必須是非空字串",
        )
    if not value or value != value.strip() or any(character.isspace() for character in value):
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file.api_key",
            "api_key 不得為空或包含空白",
        )
    if value.casefold() in _PLACEHOLDERS:
        raise CredentialError(
            "credential_file_invalid",
            "$credential_file.api_key",
            "api_key 仍是 placeholder，請填入受限 key",
        )
    return value
