#!/bin/sh
''''true
# The lines down to the closing quote are a shell script, and to Python they
# are just a string, so this file is both. "python server.py" is unaffected.
#
# A plain "#!/usr/bin/env python3" shebang is not enough. The interpreter is
# called python on some systems and python3 on others, and a name being present
# on the PATH does not mean it is a working interpreter: some systems ship a
# placeholder of that name which only prints an error. Testing whether a name
# exists therefore proves nothing - each candidate has to be asked to run
# something.
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "snapgrid: no working python found. Tried python3, python and py." >&2
echo "  Install Python 3.11 or newer, or run: <your python> -m snapgrid" >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Start snapgrid: ./server.py   (or: python -m snapgrid)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from snapgrid.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
