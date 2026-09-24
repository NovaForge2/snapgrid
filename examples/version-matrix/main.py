#!/usr/bin/env python3
"""A demo plugin with invented data, to show what history looks like.

It prints a table with one row per item and one column per environment, which
is the shape to use when comparing the same thing across several places. The
numbers are made up and no system is contacted.

The versions drift on purpose: the earlier environments change every half
minute, the middle ones every couple of minutes, and the last ones almost never.
So a run soon after the previous one produces exactly the same table and does
not use up a history slot, while a run later on produces a new snapshot you can
compare against.

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import random
import sys
import time

REPOS = [
    "payments-api",
    "orders-api",
    "customer-api",
    "notification-svc",
    "reporting-svc",
]

ENVIRONMENTS = ["ENV1", "ENV2", "ENV3", "ENV4", "ENV5", "ENV6"]

BUCKET_SECONDS = 30

# How many buckets a value stays put, for each environment in turn. The earlier
# ones move constantly, the later ones hardly ever.
STABILITY = [1, 1, 4, 4, 40, 60]


def stability_for(environment: str) -> int:
    try:
        return STABILITY[ENVIRONMENTS.index(environment)]
    except (ValueError, IndexError):
        return 10


def version_for(repo: str, environment: str, bucket: int) -> str:
    generation = bucket // stability_for(environment)
    rng = random.Random(f"{repo}|{environment}|{generation}")
    return f"{rng.randint(1, 3)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"


def main() -> int:
    bucket = int(time.time() // BUCKET_SECONDS)
    print("this is demo data, nothing is being contacted", file=sys.stderr)

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["repo"] + ENVIRONMENTS)
    for repo in REPOS:
        writer.writerow([repo] + [version_for(repo, env, bucket) for env in ENVIRONMENTS])

    print(f"{len(REPOS)} repositories across {len(ENVIRONMENTS)} environments", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
