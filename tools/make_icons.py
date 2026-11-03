#!/usr/bin/env python3
"""Generate PWA icons (192 and 512 px PNG) with zero dependencies."""

import struct
import sys
import zlib
from pathlib import Path

BLUE = (23, 74, 134)
WHITE = (255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def inside_rounded(px, py, size, radius):
    """True if point is inside the rounded-square background."""
    cx = min(max(px, radius), size - radius)
    cy = min(max(py, radius), size - radius)
    return (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2


def inside_art(px, py, size):
    """Draw fork + knife + ticket, scaled from a 100x100 design grid."""
    x = px * 100.0 / size
    y = py * 100.0 / size

    def rect(x0, y0, x1, y1):
        return x0 <= x < x1 and y0 <= y < y1

    # fork handle
    if rect(28, 46, 32, 78):
        return True
    # fork tines
    if rect(24.5, 24, 27.5, 46) or rect(30.5, 24, 33.5, 46) or rect(28, 24, 30, 46):
        return True
    # fork bridge
    if rect(24.5, 42, 33.5, 47):
        return True

    # knife handle
    if rect(66, 46, 70, 78):
        return True
    # knife blade
    if rect(66, 24, 70, 46) or rect(70, 26, 75.5, 40):
        return True

    # ticket body
    if rect(38, 48, 62, 66):
        return True
    # ticket notches (punch holes)
    if ((x - 38) ** 2 + (y - 57) ** 2) ** 0.5 < 2.6:
        return False
    if ((x - 62) ** 2 + (y - 57) ** 2) ** 0.5 < 2.6:
        return False
    # ticket text lines
    if rect(42, 53, 58, 56) or rect(42, 59, 54, 62):
        return False
    return False


def make_png(size: int) -> bytes:
    rows = []
    radius = size * 0.18
    for py in range(size):
        row = bytearray()
        row.append(0)  # filter type: none
        for px in range(size):
            if not inside_rounded(px, py, size, radius):
                row.extend(TRANSPARENT)
            elif inside_art(px, py, size):
                row.extend(WHITE + (255,))
            else:
                row.extend(BLUE + (255,))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main():
    out = Path(__file__).resolve().parent.parent / "web" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = out / f"icon-{size}.png"
        path.write_bytes(make_png(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    sys.exit(main())
