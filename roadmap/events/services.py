from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Event

WEEKDAY_TO_INT = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


def _local_day_window(tz: ZoneInfo, start_date: date, end_date: date):
    window_start = datetime.combine(start_date, time.min, tzinfo=tz)
    window_end_exclusive = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz)
    return window_start, window_end_exclusive


def _build_occurrence_record(event: Event, occ_start_local: datetime, occ_end_local: datetime, output_tz: ZoneInfo):
    start_out = occ_start_local.astimezone(output_tz)
    end_out = occ_end_local.astimezone(output_tz)
    occurrence_id = f"{event.id}#{occ_start_local.date().isoformat()}"
    routine_constraint = event.routine_constraint or {}
    return {
        "occurrence_id": occurrence_id,
        "event_id": str(event.id),
        "title": event.title,
        "event_type": event.event_type,
        "start_at": start_out,
        "end_at": end_out,
        "timezone": output_tz.key,
        "is_all_day": event.is_all_day,
        "routine_constraint": {
            "constraint_mode": routine_constraint.get("constraint_mode", "hard"),
            "buffer_before_minutes": routine_constraint.get("buffer_before_minutes", 0),
            "buffer_after_minutes": routine_constraint.get("buffer_after_minutes", 0),
            "routine_policy": routine_constraint.get("routine_policy", "block"),
        },
    }


def _intersects_window(occ_start: datetime, occ_end: datetime, window_start: datetime, window_end_exclusive: datetime):
    return occ_start < window_end_exclusive and occ_end > window_start


def _month_add(year: int, month: int, delta: int):
    raw = (year * 12 + (month - 1)) + delta
    return raw // 12, (raw % 12) + 1


def _emit_if_in_window(result: list, event: Event, occ_start: datetime, duration: timedelta, window_start: datetime, window_end_exclusive: datetime, output_tz: ZoneInfo):
    occ_end = occ_start + duration
    if _intersects_window(occ_start, occ_end, window_start, window_end_exclusive):
        result.append(_build_occurrence_record(event, occ_start, occ_end, output_tz))


def _normalize_until_date(raw_value):
    if raw_value is None or isinstance(raw_value, date):
        return raw_value
    return date.fromisoformat(str(raw_value))


def _expand_non_recurring(event: Event, result: list, duration: timedelta, window_start: datetime, window_end_exclusive: datetime, event_tz: ZoneInfo, output_tz: ZoneInfo):
    occ_start = event.start_at.astimezone(event_tz)
    _emit_if_in_window(result, event, occ_start, duration, window_start, window_end_exclusive, output_tz)


def _expand_daily(event: Event, recurrence: dict, result: list, duration: timedelta, window_start: datetime, window_end_exclusive: datetime, event_tz: ZoneInfo, output_tz: ZoneInfo):
    interval = recurrence["interval"]
    until_date = _normalize_until_date(recurrence.get("until_date"))
    max_count = recurrence.get("count")

    cursor = event.start_at.astimezone(event_tz)
    emitted = 0
    while cursor < window_end_exclusive:
        if until_date and cursor.date() > until_date:
            break
        if max_count and emitted >= max_count:
            break
        _emit_if_in_window(result, event, cursor, duration, window_start, window_end_exclusive, output_tz)
        emitted += 1
        cursor += timedelta(days=interval)


def _expand_weekly(event: Event, recurrence: dict, result: list, duration: timedelta, window_start: datetime, window_end_exclusive: datetime, event_tz: ZoneInfo, output_tz: ZoneInfo):
    interval = recurrence["interval"]
    until_date = _normalize_until_date(recurrence.get("until_date"))
    max_count = recurrence.get("count")
    by_weekday = {WEEKDAY_TO_INT[v] for v in recurrence.get("by_weekday", [])}

    series_start = event.start_at.astimezone(event_tz)
    series_week_start = series_start.date() - timedelta(days=series_start.weekday())

    emitted = 0
    cursor_date = series_start.date()
    while datetime.combine(cursor_date, series_start.timetz(), tzinfo=event_tz) < window_end_exclusive:
        if until_date and cursor_date > until_date:
            break
        if max_count and emitted >= max_count:
            break

        if cursor_date >= series_start.date():
            weeks_since_start = (cursor_date - series_week_start).days // 7
            if weeks_since_start % interval == 0 and cursor_date.weekday() in by_weekday:
                occ_start = datetime.combine(cursor_date, series_start.timetz(), tzinfo=event_tz)
                _emit_if_in_window(result, event, occ_start, duration, window_start, window_end_exclusive, output_tz)
                emitted += 1

        cursor_date += timedelta(days=1)


def _expand_monthly(event: Event, recurrence: dict, result: list, duration: timedelta, window_start: datetime, window_end_exclusive: datetime, event_tz: ZoneInfo, output_tz: ZoneInfo):
    interval = recurrence["interval"]
    until_date = _normalize_until_date(recurrence.get("until_date"))
    max_count = recurrence.get("count")

    series_start = event.start_at.astimezone(event_tz)
    anchor_day = series_start.day
    anchor_time = series_start.timetz()

    emitted = 0
    cursor_index = 0
    while True:
        if max_count and emitted >= max_count:
            break
        year, month = _month_add(series_start.year, series_start.month, cursor_index * interval)
        try:
            candidate_date = date(year, month, anchor_day)
        except ValueError:
            cursor_index += 1
            if cursor_index > 1000:
                break
            continue

        if until_date and candidate_date > until_date:
            break
        occ_start = datetime.combine(candidate_date, anchor_time, tzinfo=event_tz)
        if occ_start >= window_end_exclusive:
            break

        if occ_start >= series_start:
            _emit_if_in_window(result, event, occ_start, duration, window_start, window_end_exclusive, output_tz)
            emitted += 1

        cursor_index += 1
        if cursor_index > 1000:
            break


def expand_event_occurrences(event: Event, start_date: date, end_date: date, output_timezone: str | None = None):
    event_tz = ZoneInfo(event.timezone)
    output_tz = ZoneInfo(output_timezone) if output_timezone else event_tz
    window_start, window_end_exclusive = _local_day_window(event_tz, start_date, end_date)

    start_local = event.start_at.astimezone(event_tz)
    end_local = event.end_at.astimezone(event_tz)
    duration = end_local - start_local
    if duration.total_seconds() <= 0:
        return []

    result = []
    if event.event_type in (Event.EVENT_TYPE_ONE_TIME, Event.EVENT_TYPE_MULTI_DAY):
        _expand_non_recurring(event, result, duration, window_start, window_end_exclusive, event_tz, output_tz)
        return result

    recurrence = event.recurrence or {}
    frequency = recurrence.get("frequency")
    if frequency == "daily":
        _expand_daily(event, recurrence, result, duration, window_start, window_end_exclusive, event_tz, output_tz)
    elif frequency == "weekly":
        _expand_weekly(event, recurrence, result, duration, window_start, window_end_exclusive, event_tz, output_tz)
    elif frequency == "monthly":
        _expand_monthly(event, recurrence, result, duration, window_start, window_end_exclusive, event_tz, output_tz)
    return result


def apply_overlap_metadata(occurrences: list[dict], include_soft_conflicts: bool = True):
    for item in occurrences:
        item["overlap"] = {"has_overlap": False, "overlap_event_ids": []}

    for index, left in enumerate(occurrences):
        left_mode = (left.get("routine_constraint") or {}).get("constraint_mode", "hard")
        for right in occurrences[index + 1 :]:
            right_mode = (right.get("routine_constraint") or {}).get("constraint_mode", "hard")
            if not include_soft_conflicts and left_mode == "soft" and right_mode == "soft":
                continue
            if left["event_id"] == right["event_id"]:
                continue
            if left["start_at"] < right["end_at"] and right["start_at"] < left["end_at"]:
                left["overlap"]["has_overlap"] = True
                right["overlap"]["has_overlap"] = True
                if right["event_id"] not in left["overlap"]["overlap_event_ids"]:
                    left["overlap"]["overlap_event_ids"].append(right["event_id"])
                if left["event_id"] not in right["overlap"]["overlap_event_ids"]:
                    right["overlap"]["overlap_event_ids"].append(left["event_id"])

    for item in occurrences:
        item["overlap"]["overlap_event_ids"].sort()
        item["start_at"] = item["start_at"].isoformat()
        item["end_at"] = item["end_at"].isoformat()

    return occurrences
