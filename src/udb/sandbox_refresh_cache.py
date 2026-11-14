"""Cache a non-security-critical sandbox restart hint between GUI refreshes.

The manager still reads live Cloud Agent, Windows input pause, project grant,
and approval state on every refresh. Only the read-only setup-result JSON hint
uses this bounded, self-invalidating cache.
"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path


class SandboxRestartCache:
    RESCAN_SECONDS = 5.0
    MAX_HINT_BYTES = 16 * 1024

    def __init__(self):
        self.signature = None
        self.value = False
        self.next_read = 0.0

    def read(self, file: Path) -> bool:
        file = Path(file)
        try:
            info = file.lstat()
        except OSError:
            self.signature = None
            self.value = False
            self.next_read = 0.0
            return False

        # A broken link, redirected file, directory or abnormally large record
        # is not an actionable Windows restart signal.
        if (
            not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > self.MAX_HINT_BYTES
        ):
            self.signature = None
            self.value = False
            self.next_read = 0.0
            return False

        signature = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        now = time.monotonic()
        if signature == self.signature and now < self.next_read:
            return self.value

        # Filesystem timestamps can be coarse on external/virtual disks.
        # Refresh the cached hint periodically even if stat is unchanged.
        try:
            # Read at most 16 KiB even if a concurrent writer grows the
            # file between the lstat above and opening it.
            with file.open("rb") as stream:
                raw = stream.read(self.MAX_HINT_BYTES + 1)
            if len(raw) > self.MAX_HINT_BYTES:
                raise ValueError("Oversized sandbox restart hint")
            data = json.loads(raw.decode("utf-8-sig"))
            restart = (
                data.get("RestartNeeded") is True if isinstance(data, dict) else False
            )
        except (OSError, ValueError, UnicodeError):
            restart = False
        self.signature = signature
        self.value = restart
        self.next_read = now + self.RESCAN_SECONDS
        return restart
