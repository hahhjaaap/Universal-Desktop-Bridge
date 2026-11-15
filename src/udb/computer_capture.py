"""Pure bounded BGRX-to-PNG encoder for owner-visible Windows captures.

Accepts only an already-authorized, top-down GetDIBits buffer. This module
never enumerates windows, changes focus, captures pixels, or grants access.
"""

from __future__ import annotations

import struct
import zlib


def encode_bgrx_png(buffer, width: int, height: int) -> bytes:
    """Convert 32-bit top-down BGRX to lossless RGB PNG without a full raw copy."""
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= 1920
        or not 1 <= height <= 1440
    ):
        raise ValueError("Invalid bounded screenshot dimensions")
    src = memoryview(buffer).cast("B")
    stride = width * 4
    if len(src) != stride * height:
        raise ValueError("Mismatched BGRX buffer length")

    scanline = width * 3 + 1
    rows = bytearray(scanline * height)
    for y in range(height):
        # Copy only one scanline to a compact bytes object: strided bytes
        # slices run in C and are faster than strided memoryview assignment.
        # The temporary is at most 7,680 bytes, not another full image.
        pixel = bytes(src[y * stride : (y + 1) * stride])
        pos = y * scanline + 1
        end = pos + width * 3
        rows[pos:end:3] = pixel[2::4]  # R
        rows[pos + 1 : end : 3] = pixel[1::4]  # G
        rows[pos + 2 : end : 3] = pixel[0::4]  # B

    def chunk(kind: bytes, value: bytes) -> bytes:
        crc = zlib.crc32(value, zlib.crc32(kind)) & 0xFFFFFFFF
        return struct.pack("!I", len(value)) + kind + value + struct.pack("!I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 3))
        + chunk(b"IEND", b"")
    )
