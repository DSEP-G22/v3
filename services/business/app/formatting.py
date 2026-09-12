"""Display siblings for every money, volume, speed and date value. Ported from v2.

A model handed 8450.0 writes "8450.0"; a customer should read "LKR 8,450.00". Every function
is total: None in, a sensible string out.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from lanka_common.punctuation import normalise

UNCAPPED = -1.0


def money(amount: float | None, currency: str = "LKR") -> str:
    if amount is None:
        return f"{currency} 0.00"
    if amount < 0:
        return f"{currency} {abs(amount):,.2f} credit"
    return f"{currency} {amount:,.2f}"


def data_volume(gb: float | None) -> str:
    if gb is None:
        return "not recorded"
    if gb == UNCAPPED:
        return "Unlimited"
    if gb >= 1024:
        return f"{gb / 1024:,.2f} TB"
    if gb < 1:
        return f"{gb * 1024:,.0f} MB"
    return f"{gb:,.1f} GB"


def data_allowance(used_gb: float | None, cap_gb: float | None) -> str:
    used = data_volume(used_gb)
    if cap_gb is None or cap_gb == UNCAPPED:
        return f"{used} used on an unlimited allowance"
    return f"{used} used of {data_volume(cap_gb)}"


def speed(mbps: float | int | None) -> str:
    if mbps is None:
        return "not recorded"
    if mbps >= 1000 and float(mbps).is_integer():
        return f"{mbps / 1000:g} Gbps"
    return f"{mbps:g} Mbps"


def percent(value: float | None, places: int = 0) -> str:
    if value is None:
        return "not recorded"
    return f"{value:.{places}f}%"


def day(value: date | datetime | None) -> str:
    if value is None:
        return "not set"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%a %d %b %Y")


def moment(value: datetime | None) -> str:
    if value is None:
        return "not set"
    stamped = value.strftime("%a %d %b, %I:%M %p")
    return stamped.replace(" 0", " ").replace("AM", "am").replace("PM", "pm")


def window(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "not scheduled"
    if start.date() == end.date():
        tail = end.strftime("%I:%M %p").lstrip("0").replace("AM", "am").replace("PM", "pm")
        return f"{moment(start)} to {tail}"
    return f"{moment(start)} to {moment(end)}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def relative(value: datetime | None, now: datetime) -> str:
    """How long ago, in words, measured against the sim clock (never the wall clock)."""
    if value is None:
        return "never"
    seconds = int((_aware(now) - _aware(value)).total_seconds())
    future, seconds = seconds < 0, abs(seconds)
    if seconds < 60:
        phrase = "less than a minute"
    elif seconds < 3600:
        n = seconds // 60
        phrase = f"{n} minute{'s' if n != 1 else ''}"
    elif seconds < 86400:
        n = seconds // 3600
        phrase = f"{n} hour{'s' if n != 1 else ''}"
    else:
        n = seconds // 86400
        phrase = f"{n} day{'s' if n != 1 else ''}"
    return f"in {phrase}" if future else f"{phrase} ago"


def duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "not recorded"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def sentence_list(items: list[str]) -> str:
    clean = [normalise(str(i)) for i in items if str(i).strip()]
    if not clean:
        return "none"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def titlecase_code(code: str) -> str:
    upper_whole = {"gpon", "adsl", "fwa", "lte", "vdsl", "onu", "ont", "olt", "cpe"}
    if code.lower() in upper_whole:
        return code.upper()
    words = code.replace("-", " ").replace("_", " ").split()
    rendered = [w.upper() if w.lower() in upper_whole else w for w in words]
    if not rendered:
        return code
    head, *tail = rendered
    head = head if head.isupper() else head.capitalize()
    return " ".join([head, *tail])
