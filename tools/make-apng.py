#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "make-apng: no working python found." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Join PNG frames into one animated PNG.

    ./tools/make-apng.py out.png 500 frame1.png frame2.png ...
    ./tools/make-apng.py out.png 700,500,500,900 a.png b.png c.png d.png

The number is how long each frame is shown, in hundredths of a second. Give a
comma separated list to hold particular frames for longer - a frame someone
needs to read wants more time than one they only need to glance at.

Why this exists: an animation is the only honest way to show sorting and
filtering, and the usual tools for making one (ffmpeg, ImageMagick, gifsicle,
Pillow) are all things you have to install. This project claims you never need
to install anything, so its own documentation should not need to either.

An animated PNG is an ordinary PNG with three additions: an acTL chunk saying
how many frames there are, an fcTL chunk before each frame giving its timing,
and fdAT chunks carrying every frame after the first. The image data itself is
already compressed inside each source PNG and is copied across untouched, so
nothing is re-encoded and no quality is lost.

Every frame must have the same dimensions, bit depth and colour type.
"""

import struct
import sys
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunks(data: bytes):
    """Walk a PNG, yielding (type, payload) for each chunk."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    offset = len(SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        yield kind, payload
        offset += 12 + length          # length + type + payload + crc


def chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


class Frame:
    def __init__(self, path: Path):
        data = path.read_bytes()
        self.header = b""
        self.extras: list[tuple[bytes, bytes]] = []
        image = []
        for kind, payload in chunks(data):
            if kind == b"IHDR":
                self.header = payload
            elif kind == b"IDAT":
                image.append(payload)
            elif kind in (b"PLTE", b"tRNS", b"gAMA", b"sRGB"):
                self.extras.append((kind, payload))
        if not self.header or not image:
            raise ValueError(f"{path} has no image data")
        self.image = b"".join(image)
        self.width, self.height = struct.unpack(">II", self.header[:8])


def build(frames: list[Frame], delays: list[int], plays: int = 0) -> bytes:
    first = frames[0]
    for frame in frames[1:]:
        if frame.header != first.header:
            raise ValueError("every frame must have the same size and colour type")

    out = [SIGNATURE, chunk(b"IHDR", first.header)]
    for kind, payload in first.extras:
        out.append(chunk(kind, payload))

    # acTL: how many frames, and how many times to play (0 means for ever)
    out.append(chunk(b"acTL", struct.pack(">II", len(frames), plays)))

    sequence = 0
    for index, frame in enumerate(frames):
        delay = delays[index] if index < len(delays) else delays[-1]
        # fcTL: this frame's position, size and how long it is shown.
        # Disposal 0 keeps the previous frame; blend 0 replaces the pixels.
        out.append(chunk(b"fcTL", struct.pack(
            ">IIIIIHHBB",
            sequence, frame.width, frame.height, 0, 0,
            delay, 100, 0, 0,
        )))
        sequence += 1

        if index == 0:
            # The first frame is the still image any viewer without animation
            # support will show, so it stays an ordinary IDAT.
            out.append(chunk(b"IDAT", frame.image))
        else:
            out.append(chunk(b"fdAT", struct.pack(">I", sequence) + frame.image))
            sequence += 1

    out.append(chunk(b"IEND", b""))
    return b"".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2

    target = Path(argv[1])
    delays = [int(value) for value in argv[2].split(",")]
    sources = [Path(name) for name in argv[3:]]

    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        print(f"make-apng: no such file: {', '.join(missing)}", file=sys.stderr)
        return 1

    frames = [Frame(path) for path in sources]
    target.write_bytes(build(frames, delays))
    size = target.stat().st_size
    total = sum(delays[i] if i < len(delays) else delays[-1] for i in range(len(frames)))
    print(f"{target}: {len(frames)} frames, {frames[0].width}x{frames[0].height}, "
          f"{total / 100:.1f}s a loop, {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
