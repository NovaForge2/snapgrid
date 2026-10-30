#!/usr/bin/env python3
"""A demo plugin with invented data: one line per pod, not one per service.

This is the awkward shape. A service being replaced has two pods for a while -
the one that is going and the one that is arriving - so the table has two lines
for it, and no column tells them apart from one deployment to the next: the pod
name is new every time and the image is the thing that changed.

So the row is named by what is stable, `[table] key = ["Environment",
"Service"]`, and the two lines are merged into the row they name. Where the two
pods differ, the cell holds both values, a line each.

Nothing is contacted. The data drifts on a clock, like version-matrix: two runs
inside the same minute print the same table and do not spend a history slot,
while a run later on has moved something. The age of each pod is counted from
the clock, so it is different on every single run - which is what `[compare]
ignore` is for, and the reason the history is not full of readings of one table.

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import random
import sys
import time

ENVIRONMENTS = ["DEV", "SIT", "SIT2", "SIT3", "UAT", "PREPROD", "PROD"]

SERVICES = [
    "payments-api",
    "orders-api",
    "customer-api",
    "notification-svc",
    "reporting-svc",
    "search-indexer",
]

BUCKET_SECONDS = 60

# How many buckets a deployment stays put, per environment in turn. The early
# ones are redeployed constantly; production almost never.
STABILITY = [1, 1, 2, 2, 8, 20, 60]

SPRINT = "release/2026-sprint11"


def stability_for(environment: str) -> int:
    try:
        return STABILITY[ENVIRONMENTS.index(environment)]
    except (ValueError, IndexError):
        return 10


def generation_of(environment: str, service: str, bucket: int) -> int:
    """Which deployment of this service we are looking at."""
    return bucket // stability_for(environment)


def age(seconds: float) -> str:
    """The way a cluster writes an age: 4m, 16h42m, 2d16h."""
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def pods(environment: str, service: str, bucket: int, now: float) -> list[list[str]]:
    """The lines for one service: one pod, or two while it is being replaced."""
    generation = generation_of(environment, service, bucket)
    rng = random.Random(f"{environment}|{service}|{generation}")
    version = f"{rng.randint(1, 3)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
    ticket = rng.randint(180000, 190000)
    branch = SPRINT if rng.random() < 0.7 else f"feature/c{ticket}-{service.split('-')[0]}"
    started = now - rng.randint(5, 60 * 60 * 24 * 9)
    rows = [[
        environment, service, f"{service}-{rng.randrange(16**5):05x}",
        "1/1", "Running", str(rng.choice([0, 0, 0, 0, 1, 3, 12])),
        age(now - started), version, branch,
    ]]

    # Mid-deployment: the pod that is arriving, beside the one that is going.
    # Its image is the new one, and its own pod name is new as well - which is
    # exactly why neither of them can name the row.
    if rng.random() < 0.25:
        fresh = random.Random(f"{environment}|{service}|{generation}|new")
        healthy = fresh.random() < 0.75
        rows.append([
            environment, service, f"{service}-{fresh.randrange(16**5):05x}",
            "1/1" if healthy else "0/1",
            "Running" if healthy else "ImagePullBackOff",
            "0", age(fresh.randint(30, 60 * 90)),
            f"{version.rsplit('.', 1)[0]}.{int(version.rsplit('.', 1)[1]) + 1}",
            branch if healthy else f"feature/c{ticket}-hotfix",
        ])
    return rows


def main() -> int:
    now = time.time()
    bucket = int(now // BUCKET_SECONDS)
    print("this is demo data, no cluster is being contacted", file=sys.stderr)

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["Environment", "Service", "Pod", "Ready", "Status",
                     "Restarts", "Age", "Image", "Branch"])

    lines = 0
    for environment in ENVIRONMENTS:
        for service in SERVICES:
            for row in pods(environment, service, bucket, now):
                writer.writerow(row)
                lines += 1

    rows = len(ENVIRONMENTS) * len(SERVICES)
    print(f"{lines} pods across {rows} services", file=sys.stderr)
    if lines > rows:
        print(f"{lines - rows} of them are being replaced, so their service has two",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
