#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "make-screenshots: no working python found." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Take the screenshots the documentation uses, light and dark.

    ./server.py start --dir examples
    ./tools/make-screenshots.py                 # all of them
    ./tools/make-screenshots.py docs/demo       # one of them

Every picture in the README, in docs/ and beside each example comes from here,
so when the interface changes they are all redone in one go rather than
drifting one at a time until they show something that no longer exists.

This needs Chrome, which is the one thing in this repository that does. It is a
maintainer's tool, not part of snapgrid: nobody running snapgrid ever runs it,
and nothing it produces is needed to use the program. The pictures it writes
are committed, so a reader needs neither Chrome nor this script.

The page loads its data over the API after the document is ready, so each shot
is taken on a virtual clock that is allowed to run on for a few seconds first.
Without that the pictures are of an empty table.
"""

import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SERVER = "http://127.0.0.1:8765"

CHROMES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser",
]

# where it goes, how big, and what to show. One entry becomes two pictures.
# 1440 wide, not the 1100 these used to be. Narrower than about 1400 and the
# toolbar wraps onto a second line, which is a true picture of a small window
# but a poor picture of the interface. The README displays them at 900, so the
# extra width costs the reader nothing.
SHOTS = [
    ("docs/diff", 1440, 560, "?plugin=version-matrix&compare=4", 1),
] + [
    (f"examples/{name}/screenshot", 1440, 470, f"?plugin={name}", 1)
    for name in ("certificate-expiry", "endpoint-health", "hello-table",
                 "notes", "team-directory", "version-matrix")
]

# disk-space is not in that list and must not be put back in it. It reports on
# the machine it runs on, so a picture of it is a picture of this machine: the
# filesystems, how big they are, how full. Its README says what the table looks
# like in words instead, with invented numbers. The same goes for any example
# added later that reads the machine rather than a file or an API.


def find_chrome() -> str:
    for candidate in CHROMES:
        found = candidate if Path(candidate).exists() else shutil.which(candidate)
        if found:
            return found
    sys.exit("make-screenshots: no Chrome found. Install it, or take the "
             "pictures by hand - this tool is only a convenience.")


def shoot(chrome: str, out: Path, width: int, height: int, query: str, scale: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--screenshot={out}", f"--window-size={width},{height}",
        f"--force-device-scale-factor={scale}",
        "--virtual-time-budget=5000",
        SERVER + query,
    ], capture_output=True, text=True)
    if not out.exists():
        sys.exit(f"make-screenshots: Chrome wrote nothing for {out}\n{result.stderr}")


# The animation in the README, one frame per state. Every state here is one the
# address bar can name, which is the whole reason it can be rebuilt rather than
# recaptured by hand. The numbers are how long each frame is held, in
# hundredths of a second: a beat on the plain table, then a step per run added,
# then a long hold on the end so it can be read.
FILM = {
    # What the README opens with: the table, then the three things anybody does
    # to a table, then two other plugins so it is clear this is a page of them
    # rather than one report. Every frame is an address, which is why it can be
    # rebuilt - it was hand recorded once, and then showed a toolbar that had
    # not existed for weeks because rebuilding it meant doing all of that again
    # by hand. The sort, the filter and the search went into the address for
    # this reason as much as for sending somebody a link.
    "docs/demo": {
        "size": (1650, 750),
        "hold": "200,140,160,160,160,320",
        "frames": [
            "?plugin=hello-table",
            "?plugin=hello-table&sort=cpu_percent:desc",
            "?plugin=hello-table&sort=cpu_percent:desc&filter.environment=ENV1",
            "?plugin=hello-table&q=api",
            "?plugin=notes",
            "?plugin=version-matrix",
        ],
    },
    "docs/diff": {
        "size": (1440, 560),
        "hold": "180,110,110,140,320",
        "frames": [
            "?plugin=version-matrix",
            "?plugin=version-matrix&compare=2",
            "?plugin=version-matrix&compare=3",
            "?plugin=version-matrix&compare=4",
            "?plugin=version-matrix&compare=4&changed=1",
        ],
    },
}


def film(chrome: str, scratch: Path, films: dict) -> None:
    """Rebuild the animated GIFs from frames, through tools/make-gif.py."""
    for stem, plan in films.items():
        width, height = plan["size"]
        for theme, suffix in (("light", ""), ("dark", "-dark")):
            frames = []
            for number, query in enumerate(plan["frames"], start=1):
                frame = scratch / f"{Path(stem).name}{suffix}-{number}.png"
                shoot(chrome, frame, width, height, f"{query}&theme={theme}", 1)
                frames.append(str(frame))
            out = HERE / f"{stem}{suffix}.gif"
            subprocess.run([sys.executable, str(HERE / "tools" / "make-gif.py"),
                            str(out), plan["hold"], *frames], check=True)
            print(f"  {out.relative_to(HERE)}  {width}x{height}, {len(frames)} frames")


def main() -> int:
    # With no arguments, everything: that is the point of having one tool. Name
    # one or more stems - "docs/demo", "examples/notes" - to redo only those,
    # which is what to do when one picture is out of date and the rest are
    # fine. Taking them all would rewrite every file with the same picture at a
    # different minute, and bury the one that changed.
    wanted = sys.argv[1:]
    unknown = [name for name in wanted
               if name not in FILM and name not in {stem for stem, *_ in SHOTS}]
    if unknown:
        known = sorted({stem for stem, *_ in SHOTS} | set(FILM))
        sys.exit("make-screenshots: no picture called " + ", ".join(unknown)
                 + "\nthere is: " + ", ".join(known))

    shots = [one for one in SHOTS if not wanted or one[0] in wanted]
    films = {stem: plan for stem, plan in FILM.items() if not wanted or stem in wanted}

    chrome = find_chrome()
    print(f"chrome: {chrome}")
    for stem, width, height, query, scale in shots:
        for theme, suffix in (("light", ""), ("dark", "-dark")):
            out = HERE / f"{stem}{suffix}.png"
            joiner = "&" if "?" in query else "?"
            shoot(chrome, out, width, height, f"{query}{joiner}theme={theme}", scale)
            print(f"  {out.relative_to(HERE)}  {width}x{height}" + (f" @{scale}x" if scale > 1 else ""))
    with tempfile.TemporaryDirectory() as scratch:
        film(chrome, Path(scratch), films)

    print("\nThe server has to be running with --dir examples for these to "
          "show anything; check one before committing them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
