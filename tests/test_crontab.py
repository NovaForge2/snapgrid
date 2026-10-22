# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Reading a cron expression, and working out when it is next due.

Written against a fixed clock rather than against now, so a test that passes
in the morning still passes at midnight, and so the days a clock moves can be
visited deliberately instead of once a year by accident.
"""

import time
import unittest

from snapgrid_core.crontab import Cron, CronError, parse


def at(text: str) -> float:
    """A local wall clock time, as seconds since the epoch.

    mktime reads the local zone, which is the point: these tests are about
    what the person's clock says.
    """
    stamp = time.strptime(text, "%Y-%m-%d %H:%M")
    return time.mktime(stamp[:8] + (-1,))      # -1: let the zone decide on DST


def shown(when: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(when))


class WhatItAccepts(unittest.TestCase):
    def test_the_ordinary_shapes(self):
        for text in ("* * * * *", "0 9 * * 1-5", "*/15 * * * *", "0 0 1 * *",
                     "30 6,18 * * *", "0 9 * jan-mar mon", "0 */4 * * *"):
            parse(text)

    def test_names_for_months_and_days(self):
        self.assertEqual(parse("0 9 * * mon").weekdays, {1})
        self.assertEqual(parse("0 9 * feb *").months, {2})
        self.assertEqual(parse("0 9 * * MON-FRI").weekdays, {1, 2, 3, 4, 5})

    def test_sunday_is_nought_and_seven(self):
        self.assertEqual(parse("0 9 * * 0").weekdays, parse("0 9 * * 7").weekdays)

    def test_a_step_from_a_single_value_runs_to_the_end(self):
        # `5/10` in the minute field is 5, 15, 25, 35, 45, 55 - as cron does it.
        self.assertEqual(parse("5/10 * * * *").minutes, {5, 15, 25, 35, 45, 55})


class WhatItRefuses(unittest.TestCase):
    """A bad expression is refused with the field named, not accepted and
    then silently never due."""

    def bad(self, text, says):
        with self.assertRaises(CronError) as caught:
            parse(text)
        self.assertIn(says, str(caught.exception).lower())

    def test_the_wrong_number_of_fields(self):
        self.bad("0 9 * *", "five fields")
        self.bad("0 9 * * 1-5 extra", "five fields")
        self.bad("", "0 9 * * 1-5")

    def test_a_value_outside_its_field(self):
        self.bad("60 * * * *", "minute")
        self.bad("* 24 * * *", "hour")
        self.bad("* * 32 * *", "day of the month")
        self.bad("* * * 13 *", "month")
        self.bad("* * * * 8", "day of the week")

    def test_nonsense_in_a_field(self):
        self.bad("0 nine * * *", "hour")
        self.bad("0 9 * * fri-day", "day of the week")
        self.bad("*/0 * * * *", "step")
        self.bad("0 9 * * ", "five fields")

    def test_a_range_that_ends_before_it_starts(self):
        self.bad("0 17-9 * * *", "ends before it starts")


class WhenItIsNextDue(unittest.TestCase):
    def next_from(self, text, when):
        return shown(parse(text).next_after(at(when)))

    def test_later_the_same_day(self):
        self.assertEqual(self.next_from("0 9 * * *", "2026-03-10 07:13"),
                         "2026-03-10 09:00")

    def test_tomorrow_when_today_has_gone(self):
        self.assertEqual(self.next_from("0 9 * * *", "2026-03-10 09:30"),
                         "2026-03-11 09:00")

    def test_the_exact_minute_is_not_due_again(self):
        # Strictly after: a run at nine does not immediately find nine.
        self.assertEqual(self.next_from("0 9 * * *", "2026-03-10 09:00"),
                         "2026-03-11 09:00")

    def test_weekdays_skip_the_weekend(self):
        # 2026-03-13 is a Friday.
        self.assertEqual(self.next_from("0 9 * * 1-5", "2026-03-13 10:00"),
                         "2026-03-16 09:00")

    def test_every_quarter_hour(self):
        self.assertEqual(self.next_from("*/15 * * * *", "2026-03-10 09:07"),
                         "2026-03-10 09:15")

    def test_the_first_of_the_month(self):
        self.assertEqual(self.next_from("0 6 1 * *", "2026-03-10 09:00"),
                         "2026-04-01 06:00")

    def test_a_day_of_the_month_or_a_weekday_whichever_comes_first(self):
        # Cron's one oddity: with both restricted, either one counts. The
        # 13th of April 2026 is a Monday, and the 10th is a Friday.
        self.assertEqual(self.next_from("0 0 13 * 5", "2026-04-09 12:00"),
                         "2026-04-10 00:00")

    def test_something_that_never_comes_is_said_so_rather_than_searched_for_ever(self):
        self.assertIsNone(parse("0 0 30 2 *").next_after(at("2026-03-10 09:00")))


class DueSinceTheLastRun(unittest.TestCase):
    """What the scheduler actually asks. Catching up after the machine was
    asleep falls out of this rather than being bolted on."""

    def test_nothing_due_between_two_quiet_moments(self):
        self.assertFalse(parse("0 9 * * *").due_since(
            at("2026-03-10 09:05"), at("2026-03-10 09:30")))

    def test_the_moment_it_passes(self):
        self.assertTrue(parse("0 9 * * *").due_since(
            at("2026-03-10 08:59"), at("2026-03-10 09:00")))

    def test_a_nine_o_clock_nobody_was_awake_for_runs_once(self):
        # Machine off from eight until five past nine.
        self.assertTrue(parse("0 9 * * *").due_since(
            at("2026-03-10 08:00"), at("2026-03-10 09:05")))

    def test_and_only_once_however_long_it_was_away(self):
        # A fortnight of missed nine o'clocks is still one run, not fourteen:
        # the question is whether a moment has passed, not how many.
        cron = parse("0 9 * * *")
        self.assertTrue(cron.due_since(at("2026-03-01 09:30"), at("2026-03-15 09:05")))

    def test_time_going_backwards_is_not_a_reason_to_run(self):
        self.assertFalse(parse("* * * * *").due_since(
            at("2026-03-10 09:00"), at("2026-03-10 08:00")))


class TheDaysAClockMoves(unittest.TestCase):
    """Decided here rather than discovered in March. These run against the
    machine's own zone, so they assert the rule only where there is a jump to
    assert it against."""

    def setUp(self):
        """Find a day in this zone where an hour goes missing, and which one.

        Not by counting distinct hours - on 8 March 2026 in New York the five
        hours from midnight read 0, 1, 3, 4, 5, which is five of them and
        looks fine. The test is whether the hour you asked for is the hour you
        got, which is the actual question.
        """
        self.jump = self.missing = None
        for year in (2026, 2027):
            for month in (3, 4, 9, 10):         # north and south of the equator
                for day in range(1, 32):
                    try:
                        midnight = at(f"{year}-{month:02d}-{day:02d} 00:00")
                    except (ValueError, OverflowError):
                        continue
                    for hour in range(1, 5):
                        if time.localtime(midnight + hour * 3600).tm_hour != hour:
                            self.jump, self.missing = (year, month, day), hour
                            return

    def test_an_hour_that_does_not_exist_does_not_fire(self):
        if not self.jump:
            self.skipTest("this zone does not move its clocks")
        year, month, day = self.jump
        cron = parse(f"30 {self.missing} {day} {month} *")
        start = at(f"{year}-{month:02d}-{day:02d} 00:00")
        due = cron.next_after(start)
        # Either never, or in a later year - but not on this day.
        if due is not None:
            self.assertNotEqual(time.strftime("%Y-%m-%d", time.localtime(due)),
                                f"{year}-{month:02d}-{day:02d}")

    def test_an_ordinary_hour_on_that_day_still_fires(self):
        if not self.jump:
            self.skipTest("this zone does not move its clocks")
        year, month, day = self.jump
        due = parse(f"0 9 {day} {month} *").next_after(
            at(f"{year}-{month:02d}-{day:02d} 00:00"))
        self.assertEqual(shown(due), f"{year}-{month:02d}-{day:02d} 09:00")


class EveryMinuteIsStillCheap(unittest.TestCase):
    def test_a_weekly_schedule_does_not_take_for_ever_to_work_out(self):
        started = time.monotonic()
        parse("0 9 * * 1").next_after(at("2026-03-10 09:30"))
        self.assertLess(time.monotonic() - started, 1.0)
