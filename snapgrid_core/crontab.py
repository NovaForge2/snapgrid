# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""A five field cron expression, and when it is next due.

    minute  hour  day-of-month  month  day-of-week
    0       9     *             *      1-5          weekdays at nine

`every` measures from the end of the last run, which is right for "look at
this every so often" and wrong for "this has to exist by nine". Fifteen
minutes that start when the last run ended drift by the length of the run,
every run, and a daily report set that way is an hour late by Friday. A cron
expression names the wall clock instead.

There is no croniter here and there will not be: snapgrid exists to run where
nothing can be installed. What follows is the whole of it.

**Local time, deliberately.** The person reading the table is in it, and
"nine" means the nine on their clock. That has two consequences on the days a
clock moves, and both are decided here rather than discovered later:

* **Spring forward.** 02:30 does not exist on that day, so a schedule naming
  it does not fire. It is not moved to 03:30: a job asked for 02:30 and the
  day had no 02:30.
* **Fall back.** 02:30 happens twice. It fires on the first, and the second
  is not a new due time, because what the scheduler asks is whether a due
  moment has passed since the last run - and it has not passed twice.

Both follow from working in seconds since the epoch and asking localtime what
a moment looks like, rather than doing arithmetic on wall clock numbers.
"""

from __future__ import annotations

import time

# The fields, in order, with the range each one allows. Sunday is 0 and 7
# both, which is what every cron does and what everyone expects.
FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of the month", 1, 31),
    ("month", 1, 12),
    ("day of the week", 0, 7),
)

NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

# A search has to stop somewhere. `0 0 30 2 *` is a valid expression that is
# never due, and without a bound the scheduler would spin on it for ever.
# Four years clears a leap day, which is the longest real gap.
SEARCH_LIMIT_MINUTES = 4 * 366 * 24 * 60


class CronError(ValueError):
    """An expression that cannot be read. The message says which field."""


def _one_field(text: str, label: str, low: int, high: int) -> set[int]:
    """One field of the expression, as the set of values it allows."""
    allowed: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"the {label} field has an empty value in {text!r}")

        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"the step in the {label} field must be a "
                                f"positive number, not {step_text!r}")
            step = int(step_text)

        if part == "*":
            first, last = low, high
        elif "-" in part.lstrip("-"):
            start_text, _, end_text = part.partition("-")
            first, last = _value(start_text, label, low, high), \
                          _value(end_text, label, low, high)
            if first > last:
                raise CronError(f"the {label} range {part!r} ends before it starts")
        else:
            first = last = _value(part, label, low, high)
            if step != 1:
                last = high        # `5/10` means 5, 15, 25 ... as cron does

        allowed.update(range(first, last + 1, step))

    # Sunday is both 0 and 7, so a schedule naming either means the same day.
    if label == "day of the week" and 7 in allowed:
        allowed.discard(7)
        allowed.add(0)
    return allowed


def _value(text: str, label: str, low: int, high: int) -> int:
    text = text.strip()
    number = NAMES.get(text.lower())
    if number is None:
        if not text.isdigit():
            raise CronError(f"the {label} field does not understand {text!r}")
        number = int(text)
    if not low <= number <= high:
        raise CronError(f"the {label} field takes {low} to {high}, not {number}")
    return number


class Cron:
    """A parsed expression. Built once, asked many times."""

    __slots__ = ("text", "minutes", "hours", "days", "months", "weekdays",
                 "_every_day", "_every_weekday")

    def __init__(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise CronError('a cron expression looks like "0 9 * * 1-5" - '
                            "minute, hour, day of the month, month, day of the week")
        parts = text.split()
        if len(parts) != 5:
            raise CronError(f"a cron expression has five fields separated by spaces - "
                            f"minute, hour, day of the month, month, day of the week - "
                            f"and {text!r} has {len(parts)}")
        self.text = " ".join(parts)
        sets = [_one_field(part, label, low, high)
                for part, (label, low, high) in zip(parts, FIELDS)]
        self.minutes, self.hours, self.days, self.months, self.weekdays = sets
        # Cron's one genuine oddity: when both the day of the month and the day
        # of the week are restricted, a day matching *either* counts. With one
        # of them left as `*`, the other decides on its own. `0 0 13 * 5` is
        # every 13th and every Friday, not Friday the 13th.
        self._every_day = parts[2].strip() == "*"
        self._every_weekday = parts[4].strip() == "*"

    def __repr__(self) -> str:
        return f"Cron({self.text!r})"

    def matches(self, when: float) -> bool:
        """Whether this wall clock minute is one the expression names."""
        moment = time.localtime(when)
        if moment.tm_mon not in self.months:
            return False
        if moment.tm_hour not in self.hours or moment.tm_min not in self.minutes:
            return False

        # tm_wday is Monday 0; cron is Sunday 0.
        weekday = (moment.tm_wday + 1) % 7
        day_named = moment.tm_mday in self.days
        weekday_named = weekday in self.weekdays
        if self._every_day and self._every_weekday:
            return True
        if self._every_day:
            return weekday_named
        if self._every_weekday:
            return day_named
        return day_named or weekday_named

    def next_after(self, when: float) -> float | None:
        """The first due moment strictly after `when`, or None within four years.

        Minute by minute, in seconds since the epoch rather than in wall clock
        arithmetic, so the hours a clock skips are skipped here too and the
        hour it repeats is visited twice without being counted twice.
        """
        moment = time.localtime(when)
        # The start of the next whole minute after `when`.
        start = when - moment.tm_sec + 60
        for step in range(SEARCH_LIMIT_MINUTES):
            candidate = start + step * 60
            if self.matches(candidate):
                # Land on the exact minute, whatever the seconds had been.
                exact = time.localtime(candidate)
                if exact.tm_sec:
                    candidate -= exact.tm_sec
                return candidate
        return None

    def due_since(self, last: float, now: float) -> bool:
        """Whether a due moment fell in (last, now].

        This is the whole of the scheduling decision, and catching up after
        the machine was asleep falls out of it rather than being added: a nine
        o'clock that nobody was awake for is still a moment that has passed
        since the last run, so it runs once when snapgrid comes back - once,
        however long it was away, because one moment having passed is the
        question being asked.
        """
        if now <= last:
            return False
        due = self.next_after(last)
        return due is not None and due <= now


def parse(text: str) -> Cron:
    """A parsed expression, or CronError saying which field is wrong."""
    return Cron(text)
