"""The Persian date, because a Persian post with a Gregorian-only date reads odd.

Thirty lines of arithmetic, no dependency, no lookup tables: the same conversion
Iranian calendars have used since the algorithm was published. The tests pin it to
dates that are easy to check by hand — Nowruz, and a known ordinary day.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Tuple

MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")

WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")

_DAYS_BEFORE_MONTH = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    gy2, gm2, gd2 = gy - 1600, gm - 1, gd - 1
    day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    day_no += _DAYS_BEFORE_MONTH[gm2] + gd2
    if gm > 2 and (gy % 4 == 0 and gy % 100 != 0 or gy % 400 == 0):
        day_no += 1
    day_no -= 79
    cycles, day_no = divmod(day_no, 12053)
    jy = 979 + 33 * cycles + 4 * (day_no // 1461)
    day_no %= 1461
    if day_no >= 366:
        jy += (day_no - 1) // 365
        day_no = (day_no - 1) % 365
    for index in range(11):
        length = 31 if index < 6 else 30
        if day_no < length:
            return jy, index + 1, day_no + 1
        day_no -= length
    return jy, 12, day_no + 1


def from_datetime(when: datetime) -> Tuple[int, int, int]:
    return gregorian_to_jalali(when.year, when.month, when.day)


def format_fa(when) -> str:
    """e.g. ۳۰ شهریور ۱۴۰۵ — Persian digits, Persian month, no time zone games."""
    if isinstance(when, datetime):
        when = when.date()
    if not isinstance(when, date):
        return ""
    jy, jm, jd = gregorian_to_jalali(when.year, when.month, when.day)
    fa = "%d %s %d" % (jd, MONTHS[jm - 1], jy)
    return fa.translate({ord("0") + i: chr(0x06F0 + i) for i in range(10)})


def weekday_fa(when: date) -> str:
    # Python counts Monday as 0; the Persian week starts on Saturday, so shift by two
    # and read the tuple from there.
    return WEEKDAYS[when.weekday()]


def format_en(when) -> str:
    if isinstance(when, datetime):
        when = when.date()
    return "%d %s %d" % (when.day, when.strftime("%B"), when.year)
