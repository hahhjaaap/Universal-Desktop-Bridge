"""Conservative, locally adaptive worker budget for Windows hosts.

The Cloud Agent samples only local physical RAM and logical CPU count.
Samples run during connection startup and at most once every five seconds
on incoming requests. No telemetry, background polling, authorization or new
RPC. Missing system information never expands the ten-task ceiling.
"""

from __future__ import annotations

import ctypes
import os

_GIB = 1024**3


def windows_memory_bytes() -> tuple[int, int] | None:
    """Return (total, available) physical bytes; fail closed on other hosts."""
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return (int(status.ullTotalPhys), int(status.ullAvailPhys))
    except (AttributeError, OSError, ValueError):
        return None


def suggested_worker_budget(
    total_bytes: int | None, available_bytes: int | None, logical_cpus: int | None
) -> int:
    """Bound active Cloud RPCs, reserving RAM and a logical CPU for other apps.

    This is an intentionally conservative starting point, NOT an empirically
    established optimal worker count for any specific PC or workload.
    """
    if (
        type(total_bytes) is not int
        or type(available_bytes) is not int
        or total_bytes <= 0
        or not 0 <= available_bytes <= total_bytes
    ):
        ram_cap = 2
    elif total_bytes <= 8 * _GIB:
        ram_cap = 2
    elif total_bytes <= 12 * _GIB:
        ram_cap = 3
    elif total_bytes <= 24 * _GIB:
        ram_cap = 4
    else:
        ram_cap = 6

    if type(available_bytes) is int and available_bytes >= 0:
        if available_bytes < 2 * _GIB:
            ram_cap = min(ram_cap, 1)
        elif available_bytes < 4 * _GIB:
            ram_cap = min(ram_cap, 2)
        elif available_bytes < 6 * _GIB:
            ram_cap = min(ram_cap, 3)

    cpu_cap = (
        max(1, logical_cpus - 1)
        if type(logical_cpus) is int and logical_cpus > 0
        else 2
    )
    return max(1, min(10, ram_cap, cpu_cap))


def local_worker_budget() -> int:
    """Read local memory and CPU for bounded admission, without telemetry."""
    memory = windows_memory_bytes()
    total, available = memory if memory is not None else (None, None)
    return suggested_worker_budget(total, available, os.cpu_count())
