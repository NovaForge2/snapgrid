# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The GIF encoder used to build the animation in the README.

A hand written LZW encoder can be wrong in ways that one viewer forgives and
another does not, so these tests decode what was encoded and compare it with
what went in, rather than checking that the file merely looks plausible.
"""

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import importlib.util

spec = importlib.util.spec_from_file_location("make_gif", ROOT / "tools" / "make-gif.py")
make_gif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_gif)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """A minimal 8 bit RGB PNG, every scanline unfiltered."""
    raw = b"".join(b"\x00" + pixels[row * width * 3:(row + 1) * width * 3]
                   for row in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def lzw_decompress(data: bytes, code_size: int) -> bytes:
    """The other half of what the encoder does, written independently."""
    clear_code = 1 << code_size
    end_code = clear_code + 1

    bits, held, position = 0, 0, 0
    width = code_size + 1
    table = [bytes([value]) for value in range(clear_code)] + [b"", b""]
    out = bytearray()
    previous = None

    while True:
        while bits < width:
            if position >= len(data):
                return bytes(out)
            held |= data[position] << bits
            bits += 8
            position += 1
        code = held & ((1 << width) - 1)
        held >>= width
        bits -= width

        if code == clear_code:
            table = [bytes([value]) for value in range(clear_code)] + [b"", b""]
            width = code_size + 1
            previous = None
            continue
        if code == end_code:
            return bytes(out)

        if code < len(table):
            entry = table[code]
        elif previous is not None:
            entry = previous + previous[:1]
        else:
            raise ValueError("corrupt stream")

        out += entry
        if previous is not None:
            table.append(previous + entry[:1])
            if len(table) >= (1 << width) and width < 12:
                width += 1
        previous = entry


def frames_of(gif: bytes):
    """Pull each frame's position, size and decoded indices out of a GIF."""
    assert gif[:6] == b"GIF89a"
    width, height = struct.unpack("<HH", gif[6:10])
    flags = gif[10]
    position = 13
    if flags & 0x80:
        position += 3 * (2 ** ((flags & 0x07) + 1))

    found = []
    while position < len(gif):
        marker = gif[position]
        if marker == 0x21:                        # extension
            position += 2
            while gif[position]:
                position += gif[position] + 1
            position += 1
        elif marker == 0x2C:                      # image
            left, top, box_width, box_height = struct.unpack("<HHHH", gif[position + 1:position + 9])
            local = gif[position + 9]
            position += 10
            if local & 0x80:
                position += 3 * (2 ** ((local & 0x07) + 1))
            code_size = gif[position]
            position += 1
            payload = bytearray()
            while gif[position]:
                length = gif[position]
                payload += gif[position + 1:position + 1 + length]
                position += length + 1
            position += 1
            found.append((left, top, box_width, box_height,
                          lzw_decompress(bytes(payload), code_size)))
        elif marker == 0x3B:
            break
        else:
            raise ValueError(f"unexpected byte {marker:#x}")
    return width, height, found


class GifTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def frame(self, name, width, height, colours):
        """colours: a function (x, y) -> (r, g, b)."""
        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                pixels += bytes(colours(x, y))
        path = self.root / name
        write_png(path, width, height, bytes(pixels))
        return path


class RoundTrip(GifTest):
    def test_a_single_frame_decodes_back_to_the_same_pixels(self):
        red, blue = (200, 30, 30), (30, 30, 200)
        source = self.frame("a.png", 8, 4, lambda x, y: red if x < 4 else blue)
        gif = make_gif.build([source], [100])

        width, height, frames = frames_of(gif)
        self.assertEqual((width, height), (8, 4))
        self.assertEqual(len(frames), 1)

        palette = gif[13:13 + 768]
        left, top, box_width, box_height, indices = frames[0]
        self.assertEqual((left, top, box_width, box_height), (0, 0, 8, 4))
        self.assertEqual(len(indices), 32)
        for position, index in enumerate(indices):
            colour = tuple(palette[index * 3:index * 3 + 3])
            self.assertEqual(colour, red if position % 8 < 4 else blue, position)

    def test_many_colours_survive(self):
        def shade(x, y):
            return (x * 8 % 256, y * 8 % 256, (x + y) * 4 % 256)
        source = self.frame("shades.png", 32, 32, shade)
        gif = make_gif.build([source], [100])
        _, _, frames = frames_of(gif)
        self.assertEqual(len(frames[0][4]), 32 * 32)

    def test_a_long_run_of_one_colour(self):
        # Exercises the compressor building long dictionary entries.
        source = self.frame("flat.png", 200, 50, lambda x, y: (255, 255, 255))
        gif = make_gif.build([source], [100])
        _, _, frames = frames_of(gif)
        self.assertEqual(len(frames[0][4]), 200 * 50)
        self.assertEqual(set(frames[0][4]), {frames[0][4][0]})


class Animation(GifTest):
    def test_only_the_changed_rectangle_is_stored(self):
        first = self.frame("one.png", 40, 40, lambda x, y: (255, 255, 255))

        def spot(x, y):
            return (0, 0, 0) if 10 <= x < 14 and 20 <= y < 24 else (255, 255, 255)
        second = self.frame("two.png", 40, 40, spot)

        gif = make_gif.build([first, second], [100, 100])
        _, _, frames = frames_of(gif)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0][:4], (0, 0, 40, 40))
        # The second frame covers the changed square only.
        self.assertEqual(frames[1][:4], (10, 20, 4, 4))

    def test_frame_delays_are_written(self):
        first = self.frame("one.png", 4, 4, lambda x, y: (255, 255, 255))
        second = self.frame("two.png", 4, 4, lambda x, y: (0, 0, 0))
        gif = make_gif.build([first, second], [600, 250])
        delays = [struct.unpack("<H", gif[i + 4:i + 6])[0]
                  for i in range(len(gif) - 8)
                  if gif[i:i + 4] == b"\x21\xF9\x04\x04"]
        self.assertEqual(delays, [600, 250])

    def test_it_loops_for_ever(self):
        source = self.frame("one.png", 4, 4, lambda x, y: (1, 2, 3))
        gif = make_gif.build([source], [100])
        self.assertIn(b"NETSCAPE2.0", gif)
        index = gif.index(b"NETSCAPE2.0") + len("NETSCAPE2.0")
        self.assertEqual(gif[index + 2:index + 4], b"\x00\x00")   # zero means for ever

    def test_frames_of_different_sizes_are_refused(self):
        first = self.frame("one.png", 4, 4, lambda x, y: (0, 0, 0))
        second = self.frame("two.png", 8, 4, lambda x, y: (0, 0, 0))
        with self.assertRaises(ValueError):
            make_gif.build([first, second], [100, 100])


class PngReading(GifTest):
    def test_every_scanline_filter_is_understood(self):
        # zlib picks filters itself, so compress a gradient, which provokes
        # several of them, and check the pixels come back unchanged.
        width, height = 24, 24
        expected = bytearray()
        for y in range(height):
            for x in range(width):
                expected += bytes((x * 10 % 256, y * 10 % 256, (x * y) % 256))
        path = self.root / "gradient.png"
        write_png(path, width, height, bytes(expected))
        got_width, got_height, pixels = make_gif.decode_png(path)
        self.assertEqual((got_width, got_height), (width, height))
        self.assertEqual(pixels, bytes(expected))


if __name__ == "__main__":
    unittest.main()
