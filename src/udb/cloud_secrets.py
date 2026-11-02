"""Cloud device credentials: Windows Credential Manager, never CLI arguments."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .credentials import load_key, save_key

_DEVICE_ID = re.compile(r"[a-f0-9]{32}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}\Z")


def on_windows() -> bool:
    return os.name == "nt"


def credential_target(device_id: str) -> str:
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise ValueError("Invalid device ID")
    return "UniversalDesktopBridge/Cloud/" + device_id


def validate_token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError("Invalid device token")
    return value


def token_file(home: Path) -> Path:
    return Path(home) / "cloud-device-token"


def read_token_file(path: Path) -> str:
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 512:
        raise ValueError("Invalid token file")
    return validate_token(file.read_text(encoding="ascii").strip())


def save_device_token(home: Path, device_id: str, value: str) -> None:
    target = credential_target(device_id)
    token = validate_token(value)
    if on_windows():
        save_key(token, target=target)
        return
    # Linux CI and source-only tests. UDB production is Windows-only.
    folder = Path(home)
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        token_file(folder), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(token + "\n")


def load_device_token(home: Path, device_id: str) -> str:
    target = credential_target(device_id)
    if on_windows():
        return validate_token(load_key(target=target))
    return read_token_file(token_file(home))


def remove_device_token(home: Path, device_id: str) -> None:
    target = credential_target(device_id)
    if on_windows():
        import win32cred

        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except win32cred.error:
            pass
    else:
        token_file(home).unlink(missing_ok=True)
