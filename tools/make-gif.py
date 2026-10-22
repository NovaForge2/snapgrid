#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "make-gif: no working python found." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Join PNG frames into an animated GIF.

    ./tools/make-gif.py out.gif 500 frame1.png frame2.png ...
    ./tools/make-gif.py out.gif 600,500,450 a.png b.png c.png

The number is how long each frame is shown, in hundredths of a second; give a
comma separated list to hold particular frames for longer.

Why not just use an animated PNG, which loses no colour at all: because plenty
of browsers on locked down machines will not animate one, and show the first
frame instead. Those machines are exactly the ones this project is for, so the
documentation has to work there. A GIF animates everywhere.

Why not ffmpeg or ImageMagick or Pillow, which would do this in one line: they
have to be installed, and the claim this project makes is that you never have
to install anything. Its own documentation should not need an exception.

So everything here is the standard library: zlib unpacks the PNG frames, the
colours are reduced to the 256 a GIF allows, and the result is compressed with
LZW, which is what a GIF is. Screenshots of an interface use very few colours -
around a thousand, of which 256 cover over 99% of the pixels - so the reduction
is invisible in practice. A photograph would not survive it nearly as well.
"""

import collections
import struct
import sys
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


# ----- reading a PNG ------------------------------------------------------

def decode_png(path: Path) -> tuple[int, int, bytes]:
    """Return width, height and pixels as three bytes each, RGB."""
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG")

    offset, parts, header = len(PNG_SIGNATURE), [], None
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            header = payload
        elif kind == b"IDAT":
            parts.append(payload)
        offset += 12 + length

    if header is None or not parts:
        raise ValueError(f"{path} has no image data")
    width, height, depth, colour = struct.unpack(">IIBB", header[:10])
    if depth != 8 or colour not in CHANNELS:
        raise ValueError(f"{path}: only 8 bit PNGs are supported")

    channels = CHANNELS[colour]
    return width, height, _unfilter(zlib.decompress(b"".join(parts)),
                                    width, height, channels)


def _unfilter(raw: bytes, width: int, height: int, channels: int) -> bytes:
    """Undo the per scanline filters a PNG applies before compressing."""
    stride = width * channels
    out = bytearray()
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        method = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride

        if method == 1:                                   # left
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif method == 2:                                 # above
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif method == 3:                                 # average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif method == 4:                                 # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else
                                      b if pb <= pc else c)) & 255
        out += line
        previous = line

    if channels == 3:
        return bytes(out)
    # Drop alpha or expand grey, so every frame is plain RGB.
    pixels = bytearray()
    for i in range(0, len(out), channels):
        if channels == 4:
            pixels += out[i:i + 3]
        elif channels == 1:
            pixels += bytes((out[i], out[i], out[i]))
        else:
            pixels += bytes((out[i], out[i], out[i]))
    return bytes(pixels)


# ----- reducing to the 256 colours a GIF allows ---------------------------

def build_palette(frames: list[bytes]) -> tuple[list[tuple[int, int, int]], dict]:
    counts: collections.Counter = collections.Counter()
    for pixels in frames:
        for i in range(0, len(pixels), 3):
            counts[pixels[i:i + 3]] += 1

    chosen = [tuple(colour) for colour, _ in counts.most_common(256)]
    while len(chosen) < 256:
        chosen.append((0, 0, 0))

    # Every colour that did not make the table maps to its nearest neighbour.
    # There are only a few thousand in a screenshot, so this is quick and the
    # result is exact for the colours that matter.
    lookup = {}
    for colour in counts:                       # colour is the raw three bytes
        red, green, blue = colour[0], colour[1], colour[2]
        best, distance = 0, None
        for index, candidate in enumerate(chosen):
            gap = ((red - candidate[0]) ** 2 + (green - candidate[1]) ** 2
                   + (blue - candidate[2]) ** 2)
            if distance is None or gap < distance:
                best, distance = index, gap
                if gap == 0:
                    break
        lookup[colour] = best
    return chosen, lookup


def to_indices(pixels: bytes, lookup: dict) -> bytearray:
    indices = bytearray(len(pixels) // 3)
    for position in range(len(indices)):
        indices[position] = lookup[pixels[position * 3:position * 3 + 3]]
    return indices


# ----- LZW, which is what makes a GIF a GIF -------------------------------

def lzw_compress(indices: bytes, code_size: int) -> bytes:
    clear_code = 1 << code_size
    end_code = clear_code + 1

    table = {bytes([value]): value for value in range(clear_code)}
    next_code = end_code + 1
    width = code_size + 1

    out = bytearray()
    bits = 0
    held = 0

    def emit(code: int) -> None:
        nonlocal bits, held
        held |= code << bits
        bits += width
        while bits >= 8:
            out.append(held & 255)
            held >>= 8
            bits -= 8

    emit(clear_code)
    current = b""
    for value in indices:
        candidate = current + bytes([value])
        if candidate in table:
            current = candidate
            continue
        emit(table[current])
        if next_code < 4096:
            table[candidate] = next_code
            next_code += 1
            if next_code > (1 << width) and width < 12:
                width += 1
        else:
            emit(clear_code)
            table = {bytes([v]): v for v in range(clear_code)}
            next_code = end_code + 1
            width = code_size + 1
        current = bytes([value])

    if current:
        emit(table[current])
    emit(end_code)
    if bits:
        out.append(held & 255)
    return bytes(out)


def sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(data), 255):
        piece = data[start:start + 255]
        out.append(len(piece))
        out += piece
    out.append(0)
    return bytes(out)


# ----- assembling the file ------------------------------------------------

def changed_area(previous: bytearray, current: bytearray, width: int, height: int):
    """The smallest rectangle covering everything that differs."""
    top, bottom = None, None
    for row in range(height):
        start = row * width
        if previous[start:start + width] != current[start:start + width]:
            top = row if top is None else top
            bottom = row
    if top is None:
        return None

    left, right = width, -1
    for row in range(top, bottom + 1):
        start = row * width
        for column in range(width):
            if previous[start + column] != current[start + column]:
                left = min(left, column)
                break
        for column in range(width - 1, -1, -1):
            if previous[start + column] != current[start + column]:
                right = max(right, column)
                break
    return left, top, right - left + 1, bottom - top + 1


def build(paths: list[Path], delays: list[int]) -> bytes:
    decoded = [decode_png(path) for path in paths]
    width, height = decoded[0][0], decoded[0][1]
    for path, (w, h, _) in zip(paths, decoded):
        if (w, h) != (width, height):
            raise ValueError(f"{path} is {w}x{h}, but the first frame is {width}x{height}")

    palette, lookup = build_palette([pixels for _, _, pixels in decoded])
    frames = [to_indices(pixels, lookup) for _, _, pixels in decoded]

    out = bytearray(b"GIF89a")
    out += struct.pack("<HH", width, height)
    out += bytes((0xF7, 0, 0))                   # global table, 256 colours
    for red, green, blue in palette:
        out += bytes((red, green, blue))
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"   # loop for ever

    previous = None
    for index, indices in enumerate(frames):
        delay = delays[index] if index < len(delays) else delays[-1]

        if previous is None:
            left, top, box_width, box_height = 0, 0, width, height
            payload = indices
        else:
            area = changed_area(previous, indices, width, height)
            if area is None:                      # identical to the frame before
                left, top, box_width, box_height = 0, 0, 1, 1
                payload = bytearray(indices[:1])
            else:
                left, top, box_width, box_height = area
                payload = bytearray()
                for row in range(top, top + box_height):
                    start = row * width + left
                    payload += indices[start:start + box_width]

        out += b"\x21\xF9\x04\x04" + struct.pack("<H", delay) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHH", left, top, box_width, box_height) + b"\x00"
        out += bytes((8,)) + sub_blocks(lzw_compress(bytes(payload), 8))
        previous = indices

    out += b"\x3B"
    return bytes(out)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2

    target = Path(argv[1])
    delays = [int(value) for value in argv[2].split(",")]
    sources = [Path(name) for name in argv[3:]]

    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        print(f"make-gif: no such file: {', '.join(missing)}", file=sys.stderr)
        return 1

    target.write_bytes(build(sources, delays))
    total = sum(delays[i] if i < len(delays) else delays[-1] for i in range(len(sources)))
    print(f"{target}: {len(sources)} frames, {total / 100:.1f}s a loop, "
          f"{target.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
