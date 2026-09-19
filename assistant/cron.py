"""Minimal 5-field cron parser for the in-process scheduler (offline, no deps).

Fields: minute hour day-of-month month day-of-week. All datetimes are naive local
wall-clock time. Supported per-field syntax, combined with commas::

    *       full range
    N       exact value
    */s     full range stepped
    N-M     inclusive range
    N-M/s   stepped range

``dow`` uses 0=Sunday .. 6=Saturday; ``7`` is accepted and normalised to ``0``.
Python ``weekday()`` (Monday=0) is mapped via ``(weekday() + 1) % 7``.
"""

from datetime import datetime, timedelta


class CronError(ValueError):
    pass


_FIELDS = ("minute", "hour", "dom", "month", "dow")
_RANGES = {"minute": (0, 59), "hour": (0, 23), "dom": (1, 31), "month": (1, 12), "dow": (0, 6)}


def _parse_field(name, token):
    low, high = _RANGES[name]
    raw_high = 7 if name == "dow" else high
    values = set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            raise CronError("调度表达式含空字段")
        step = 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"步长无效: {part}")
            step = int(step_text)
            part = base
        if part == "*":
            start, end = low, raw_high
        elif "-" in part:
            a, b = part.split("-", 1)
            if not a.isdigit() or not b.isdigit():
                raise CronError(f"范围无效: {part}")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise CronError(f"字段无效: {part}")
        if start < low or end > raw_high or start > end:
            raise CronError(f"取值越界: {part}")
        values.update(range(start, end + 1, step))
    if name == "dow":
        values = {0 if v == 7 else v for v in values}
    return values


def parse_expr(expr):
    """Return ``{"minute": set, "hour": set, "dom": set, "month": set, "dow": set}``."""
    parts = str(expr).strip().split()
    if len(parts) != 5:
        raise CronError("调度表达式需 5 个字段（分 时 日 月 周）")
    return {name: _parse_field(name, token) for name, token in zip(_FIELDS, parts)}


def _day_matches(doms, dows, day, weekday, dom_restricted, dow_restricted):
    # Vixie cron: when both dom and dow are restricted, a day matches when either does.
    if dom_restricted and dow_restricted:
        return (day in doms) or (weekday in dows)
    if dom_restricted:
        return day in doms
    if dow_restricted:
        return weekday in dows
    return True


def next_run(expr, after):
    """Return the first datetime strictly after ``after`` matching ``expr``."""
    fields = parse_expr(expr)
    minutes, hours, doms, months, dows = (fields[n] for n in _FIELDS)
    dom_restricted = doms != set(range(1, 32))
    dow_restricted = dows != set(range(7))
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    horizon = after + timedelta(days=4 * 366)
    while candidate <= horizon:
        if candidate.month not in months:
            candidate = (candidate.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
        elif not _day_matches(doms, dows, candidate.day, (candidate.weekday() + 1) % 7, dom_restricted, dow_restricted):
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
        elif candidate.hour not in hours:
            candidate = candidate.replace(minute=0) + timedelta(hours=1)
        elif candidate.minute not in minutes:
            candidate += timedelta(minutes=1)
        else:
            return candidate
    raise CronError("调度表达式在时间范围内无法匹配（检查日期与星期的组合）")
