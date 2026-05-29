import re
from datetime import timedelta
from typing import Dict, Tuple
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from authentication.models import Profile, UserPersonalDetails
from goal.models import Goal, Task

from .date_context import get_date_context, is_birthday
from .models import DailyRitualLog, RitualMessageHistory, UserRitualProfile
from .templates import (
    DATE_TEMPLATES,
    MESSAGE_TEMPLATES,
    MILESTONE_TEMPLATES,
    SPECIAL_MESSAGE_TEMPLATES,
    SPECIAL_PRIORITY,
    TRIGGER_MESSAGE_TEMPLATES,
    get_milestone_key,
)


ROUTINE_KEYS: Tuple[str, ...] = ("water", "coffee", "freshen", "no_phone", "stretch")
TASK_RESPONSE_MAP: Dict[str, str] = {
    "done": "night_task_done",
    "partial": "night_task_missed",
    "missed": "night_task_missed",
    "strong": "night_task_done",
    "okay": "night_task_done",
    "rough": "night_task_missed",
}
TODAY_TASK_PHRASES: Dict[str, str] = {
    "bro": "Today's one thing: {task}.",
    "gentle": "Today's one thing is {task}.",
    "soft_girl": "Today's little mission is {task}.",
    "coach": "Primary task today: {task}.",
}
DEFAULT_TIMEZONE = "Asia/Kathmandu"
TRIGGER_WEB_BUTTON_CLICKED = "WEB_BUTTON_CLICKED"
TRIGGER_MORNING_ALARM_DISMISSED = "MORNING_ALARM_DISMISSED"
TRIGGER_NIGHT_ALARM_DISMISSED = "NIGHT_ALARM_DISMISSED"
TRIGGER_MILESTONE_REACHED = "MILESTONE_REACHED"
TRIGGER_STREAK_RECOVERED = "STREAK_RECOVERED"
TRIGGER_SPECIAL_DAY = "SPECIAL_DAY_TRIGGER"
TRIGGER_WEB_MORNING_BUTTON_CLICKED = "WEB_MORNING_BUTTON_CLICKED"
TRIGGER_WEB_NIGHT_BUTTON_CLICKED = "WEB_NIGHT_BUTTON_CLICKED"
VALID_TRIGGER_TYPES: Tuple[str, ...] = (
    TRIGGER_WEB_BUTTON_CLICKED,
    TRIGGER_MORNING_ALARM_DISMISSED,
    TRIGGER_NIGHT_ALARM_DISMISSED,
    TRIGGER_MILESTONE_REACHED,
    TRIGGER_STREAK_RECOVERED,
    TRIGGER_SPECIAL_DAY,
    TRIGGER_WEB_MORNING_BUTTON_CLICKED,
    TRIGGER_WEB_NIGHT_BUTTON_CLICKED,
)
TIME_SEGMENTS: Tuple[Tuple[int, int, str], ...] = (
    (0, 9, "morning"),
    (10, 16, "afternoon"),
    (17, 20, "evening"),
    (21, 23, "night"),
)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001faff"
    "\u2600-\u27bf"
    "\ufe0f"
    "\u200d"
    "]+",
    flags=re.UNICODE,
)

def get_or_create_ritual_profile(user):
    return UserRitualProfile.objects.get_or_create(user=user)[0]


def get_or_create_daily_log(user, log_date=None):
    log_date = log_date or timezone.localdate()
    log, _ = DailyRitualLog.objects.get_or_create(user=user, date=log_date)
    return log


def get_user_timezone(user, header_timezone=None):
    candidate = (header_timezone or "").strip()
    if candidate:
        try:
            ZoneInfo(candidate)
            return candidate
        except Exception:
            pass

    profile, _ = Profile.objects.get_or_create(user=user)
    candidate = (profile.timezone or DEFAULT_TIMEZONE).strip()
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        profile.timezone = DEFAULT_TIMEZONE
        profile.save(update_fields=["timezone"])
        return DEFAULT_TIMEZONE


def get_local_now(user, header_timezone=None):
    timezone_name = get_user_timezone(user, header_timezone=header_timezone)
    return timezone.now().astimezone(ZoneInfo(timezone_name))


def get_time_segment_for_local_hour(hour):
    for start_hour, end_hour, segment in TIME_SEGMENTS:
        if start_hour <= hour <= end_hour:
            return segment
    return "morning"


def get_ritual_time_context(user, header_timezone=None):
    local_now = get_local_now(user, header_timezone=header_timezone)
    return {
        "timezone": str(local_now.tzinfo),
        "local_date": local_now.date(),
        "local_time": local_now.time().replace(second=0, microsecond=0),
        "time_segment": get_time_segment_for_local_hour(local_now.hour),
    }


def clean_message_for_tts(message):
    cleaned = EMOJI_PATTERN.sub("", message or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_user_birthday(user, profile, current_date):
    if profile.date_of_birth and profile.date_of_birth.month == current_date.month and profile.date_of_birth.day == current_date.day:
        return True
    personal_details = UserPersonalDetails.objects.filter(user=user).only("date_of_birth").first()
    if not personal_details:
        return False
    return (
        personal_details.date_of_birth.month == current_date.month
        and personal_details.date_of_birth.day == current_date.day
    )


def _get_trigger_day_number(user, current_date):
    goal_day_ctx = _get_goal_day_context(user, current_date)
    if goal_day_ctx["day_number"]:
        return goal_day_ctx["day_number"], goal_day_ctx["total_days"]

    previous_days = (
        RitualMessageHistory.objects.filter(user=user, shown_on__lt=current_date)
        .values("shown_on")
        .distinct()
        .count()
    )
    return previous_days + 1, None


def _has_missed_day(user, current_date):
    previous = RitualMessageHistory.objects.filter(user=user, shown_on__lt=current_date).order_by("-shown_on").first()
    if not previous:
        return False
    return (current_date - previous.shown_on).days > 1


def _get_special_template_key(user, profile, trigger_type, current_date):
    day_number, total_days = _get_trigger_day_number(user, current_date)
    checks = {
        "birthday": _is_user_birthday(user, profile, current_date),
        "new_year": current_date.month == 1 and current_date.day == 1,
        "milestone": trigger_type == TRIGGER_MILESTONE_REACHED
        or (total_days is not None and day_number == max(total_days // 2, 1)),
        "day_30": day_number == 30,
        "day_21": day_number == 21,
        "day_7": day_number == 7,
        "missed_day": trigger_type == TRIGGER_STREAK_RECOVERED or _has_missed_day(user, current_date),
        "monday": current_date.weekday() == 0,
    }
    for key in SPECIAL_PRIORITY:
        if checks[key]:
            return key
    return None


def _get_previous_day_template_id(user, current_date):
    previous = RitualMessageHistory.objects.filter(user=user, shown_on__lt=current_date).order_by("-shown_on").first()
    return previous.template_id if previous else None


def _pick_template_from_pool(user, trigger_type, candidates, current_date):
    previous_day_template_id = _get_previous_day_template_id(user, current_date)
    used_template_ids = set(
        RitualMessageHistory.objects.filter(user=user, trigger_type=trigger_type)
        .values_list("template_id", flat=True)
    )
    candidate_ids = [candidate["id"] for candidate in candidates]

    available = [
        candidate
        for candidate in candidates
        if candidate["id"] not in used_template_ids and candidate["id"] != previous_day_template_id
    ]
    if available:
        return available[0]

    reset_available = [candidate for candidate in candidates if candidate["id"] != previous_day_template_id]
    if reset_available:
        return reset_available[0]

    return candidates[0]


def build_trigger_message(user, trigger_type, header_timezone=None):
    profile = get_or_create_ritual_profile(user)
    time_ctx = get_ritual_time_context(user, header_timezone=header_timezone)
    current_date = time_ctx["local_date"]
    time_segment = time_ctx["time_segment"]
    special_key = _get_special_template_key(user, profile, trigger_type, current_date)

    if special_key:
        special_template = SPECIAL_MESSAGE_TEMPLATES[special_key]
        candidates = [
            {
                "id": special_template["id"],
                "message": special_template["message"],
            }
        ]
    else:
        candidates = [
            template
            for template in TRIGGER_MESSAGE_TEMPLATES[time_segment]
            if template["tone"] == profile.ritual_tone
        ]

    template = _pick_template_from_pool(user, trigger_type, candidates, current_date)
    return {
        "message": template["message"],
        "tone": profile.ritual_tone,
        "voice_enabled": profile.ritual_active,
        "template_id": template["id"],
        "trigger_type": trigger_type,
        "time_segment": time_segment,
        "shown_on": current_date,
    }


def trigger_ritual_message(user, trigger_type, header_timezone=None):
    payload = build_trigger_message(user, trigger_type, header_timezone=header_timezone)
    RitualMessageHistory.objects.create(
        user=user,
        trigger_type=trigger_type,
        template_id=payload["template_id"],
        message=payload["message"],
        tone=payload["tone"],
        shown_on=payload["shown_on"],
    )
    get_or_create_daily_log(user, payload["shown_on"])
    return {
        "message": payload["message"],
        "tone": payload["tone"],
        "voice_enabled": payload["voice_enabled"],
        "template_id": payload["template_id"],
        "time_segment": payload["time_segment"],
        "trigger_type": payload["trigger_type"],
    }


def get_wake_status(wake_delta):
    if wake_delta is None:
        return "on_time"
    if wake_delta <= -5:
        return "early"
    if wake_delta <= 15:
        return "on_time"
    return "late"


def get_streak_key(streak):
    for threshold in (30, 14, 7, 3):
        if streak >= threshold:
            return threshold
    return None


def get_routine_suggestion(current_date=None):
    date_ctx = get_date_context(current_date)
    return ROUTINE_KEYS[date_ctx["day_of_year"] % len(ROUTINE_KEYS)]


def _pick_available_index(used_indices, total, last_index):
    available = [idx for idx in range(total) if idx not in used_indices and idx != last_index]
    if available:
        return available[0]
    reset_available = [idx for idx in range(total) if idx != last_index]
    if reset_available:
        return reset_available[0]
    return 0


def smart_pick(user, slot_key, variants, log=None):
    if not variants:
        return None
    log = log or get_or_create_daily_log(user)
    previous_logs = DailyRitualLog.objects.filter(user=user, date__lt=log.date).order_by("-date")
    used_indices = []
    last_index = None
    for previous_log in previous_logs:
        previous_index = previous_log.shown_variants.get(slot_key)
        if previous_index is None:
            continue
        if last_index is None:
            last_index = previous_index
        if previous_index in used_indices:
            break
        used_indices.append(previous_index)
        if len(used_indices) >= len(variants):
            break
    chosen_index = _pick_available_index(used_indices, len(variants), last_index)
    shown_variants = dict(log.shown_variants or {})
    shown_variants[slot_key] = chosen_index
    log.shown_variants = shown_variants
    log.save(update_fields=["shown_variants", "updated_at"])
    return variants[chosen_index]


def get_date_line(user, tone, date_ctx, profile=None, log=None):
    profile = profile or get_or_create_ritual_profile(user)
    log = log or get_or_create_daily_log(user, date_ctx["date"])

    if is_birthday(profile, date_ctx["date"]):
        return DATE_TEMPLATES["birthday"][tone]
    if date_ctx["is_jan_1"]:
        return DATE_TEMPLATES["new_year"][tone]
    if date_ctx["is_dec_31"]:
        return DATE_TEMPLATES["new_year_eve"][tone]
    if date_ctx["is_monday"]:
        return smart_pick(user, f"date_monday_{tone}", DATE_TEMPLATES["monday"][tone], log=log)
    if date_ctx["is_friday"]:
        return smart_pick(user, f"date_friday_{tone}", DATE_TEMPLATES["friday"][tone], log=log)
    if date_ctx["is_sunday"]:
        return smart_pick(user, f"date_sunday_{tone}", DATE_TEMPLATES["sunday"][tone], log=log)
    if date_ctx["day_of_year"] % 5 == 0:
        return DATE_TEMPLATES[date_ctx["season"]][tone]
    return None


def _time_to_minutes(value):
    if value is None:
        return None
    return value.hour * 60 + value.minute


def _get_previous_log(user, log_date):
    return DailyRitualLog.objects.filter(user=user, date__lt=log_date).order_by("-date").first()


def _get_current_goal(user):
    return (
        Goal.objects.filter(user=user)
        .exclude(status__in=["completed", "cancelled"])
        .order_by("target_date", "created_at")
        .first()
    )


def _get_goal_day_context(user, current_date=None):
    current_date = current_date or timezone.localdate()
    goal = _get_current_goal(user)
    if not goal or not goal.start_date or not goal.target_date:
        return {"goal": goal, "day_number": None, "total_days": None}
    total_days = max((goal.target_date - goal.start_date).days + 1, 1)
    day_number = (current_date - goal.start_date).days + 1
    if day_number < 1:
        return {"goal": goal, "day_number": 1, "total_days": total_days}
    return {"goal": goal, "day_number": day_number, "total_days": total_days}


def get_goal_tasks_for_user(user, limit=6, current_date=None):
    current_date = current_date or timezone.localdate()
    tasks = (
        Task.objects.filter(subgoal__milestone__goal__user=user)
        .exclude(status__in=["completed", "skipped"])
        .filter(Q(scheduled_date__isnull=True) | Q(scheduled_date__gte=current_date))
        .select_related("subgoal__milestone__goal")
        .order_by("scheduled_date", "display_order", "created_at")
    )
    titles = []
    for task in tasks:
        title = (task.title or "").strip()
        if not title or title in titles:
            continue
        titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def get_task_for_today(user, current_date=None):
    current_date = current_date or timezone.localdate()
    previous_log = _get_previous_log(user, current_date)
    if previous_log and previous_log.tomorrow_intent:
        return previous_log.tomorrow_intent.strip()
    tasks = get_goal_tasks_for_user(user, limit=1, current_date=current_date)
    return tasks[0] if tasks else None


def calculate_ritual_streak(user, current_date=None):
    current_date = current_date or timezone.localdate()
    streak = 0
    logs = DailyRitualLog.objects.filter(user=user, date__lte=current_date).order_by("-date")
    expected_date = current_date
    for log in logs:
        if log.date != expected_date:
            break
        has_activity = any(
            [
                log.morning_session_completed,
                log.night_session_completed,
                log.actual_wake_time,
                log.tomorrow_intent,
            ]
        )
        if not has_activity:
            break
        streak += 1
        expected_date = expected_date - timedelta(days=1)
    return streak


def _build_today_task_line(task, tone):
    if not task:
        return None
    return TODAY_TASK_PHRASES[tone].format(task=task)


def _build_morning_reference(log):
    if not log:
        return None
    if log.morning_energy:
        return f"This morning you marked your energy as {log.morning_energy}."
    if log.actual_wake_time:
        return "You answered the morning ritual today."
    return None


def _format_alarm_time(value):
    if value is None:
        return "06:15"
    return value.strftime("%I:%M %p").lstrip("0")


def build_morning_message(user, user_data=None):
    user_data = user_data or {}
    current_date = user_data.get("current_date") or timezone.localdate()
    date_ctx = user_data.get("date_ctx") or get_date_context(current_date)
    profile = user_data.get("profile") or get_or_create_ritual_profile(user)
    log = user_data.get("log") or get_or_create_daily_log(user, current_date)
    previous_log = user_data.get("previous_log") or _get_previous_log(user, current_date)
    tone = user_data.get("tone") or profile.ritual_tone

    if log.snooze_count >= 2:
        wake_line = smart_pick(user, f"snooze_{tone}", MESSAGE_TEMPLATES["snooze"][tone], log=log)
    else:
        wake_key = get_wake_status(log.wake_delta_minutes)
        wake_line = smart_pick(
            user,
            f"wake_{wake_key}_{tone}",
            MESSAGE_TEMPLATES["wake"][wake_key][tone],
            log=log,
        )

    parts = [wake_line]
    date_line = get_date_line(user, tone, date_ctx, profile=profile, log=log)
    if date_line:
        parts.append(date_line)

    streak = calculate_ritual_streak(user, current_date)
    streak_key = get_streak_key(streak)
    if streak_key:
        parts.append(MESSAGE_TEMPLATES["streak"][streak_key][tone])

    if previous_log and previous_log.yesterday_task_reflection:
        reaction_variants = MESSAGE_TEMPLATES["task"][previous_log.yesterday_task_reflection][tone]
        parts.append(
            smart_pick(
                user,
                f"task_{previous_log.yesterday_task_reflection}_{tone}",
                reaction_variants,
                log=log,
            )
        )

    routine_key = get_routine_suggestion(current_date)
    parts.append(MESSAGE_TEMPLATES["routine"][routine_key][tone])

    task_today = get_task_for_today(user, current_date=current_date)
    task_line = _build_today_task_line(task_today, tone)
    if task_line:
        parts.append(task_line)

    goal_day_ctx = _get_goal_day_context(user, current_date)
    milestone_key = get_milestone_key(goal_day_ctx["day_number"], goal_day_ctx["total_days"])
    if milestone_key:
        parts.append(MILESTONE_TEMPLATES[milestone_key][tone])
    else:
        parts.append(smart_pick(user, f"closer_{tone}", MESSAGE_TEMPLATES["closer"][tone], log=log))

    return {
        "message": " ".join(part for part in parts if part),
        "task_today": task_today,
        "streak": streak,
        "routine_key": routine_key,
        "milestone_key": milestone_key,
    }


def build_night_open(user, tone=None, current_date=None):
    current_date = current_date or timezone.localdate()
    profile = get_or_create_ritual_profile(user)
    tone = tone or profile.ritual_tone
    log = get_or_create_daily_log(user, current_date)
    open_line = smart_pick(user, f"night_open_{tone}", MESSAGE_TEMPLATES["night_open"][tone], log=log)
    morning_reference = _build_morning_reference(log)
    parts = [open_line]
    if morning_reference:
        parts.append(morning_reference)
    return " ".join(part for part in parts if part)


def build_night_task_response(user, tone, task_status, current_date=None):
    current_date = current_date or timezone.localdate()
    log = get_or_create_daily_log(user, current_date)
    slot_name = TASK_RESPONSE_MAP.get(task_status, "night_task_missed")
    variants = MESSAGE_TEMPLATES[slot_name][tone]
    return smart_pick(user, f"{slot_name}_{tone}", variants, log=log)


def build_night_intent_confirmed(tone, task):
    task = (task or "").strip()
    if not task:
        task = "check your goal dashboard"
    return MESSAGE_TEMPLATES["night_intent_confirmed"][tone].format(task=task)


def build_night_closer(tone, day_number, alarm_time):
    return MESSAGE_TEMPLATES["night_closer"][tone].format(
        day=day_number or 1,
        time=_format_alarm_time(alarm_time),
    )


def set_wake_delta_for_log(log, alarm_time):
    if not log.actual_wake_time or not alarm_time:
        log.wake_delta_minutes = None
        return None
    wake_minutes = _time_to_minutes(log.actual_wake_time)
    alarm_minutes = _time_to_minutes(alarm_time)
    if wake_minutes is None or alarm_minutes is None:
        log.wake_delta_minutes = None
        return None
    log.wake_delta_minutes = wake_minutes - alarm_minutes
    return log.wake_delta_minutes


def mark_morning_entry(log, alarm_time):
    if not log.actual_wake_time:
        log.actual_wake_time = timezone.localtime().time().replace(second=0, microsecond=0)
    set_wake_delta_for_log(log, alarm_time)
    log.save(update_fields=["actual_wake_time", "wake_delta_minutes", "updated_at"])
    log.ritual_streak_day = calculate_ritual_streak(log.user, current_date=log.date)
    log.save(update_fields=["ritual_streak_day", "updated_at"])
    return log


def mark_morning_completed(log, energy, alarm_time):
    log.morning_energy = energy
    log.morning_session_completed = True
    log.morning_session_time = timezone.localtime().time().replace(second=0, microsecond=0)
    if not log.actual_wake_time:
        log.actual_wake_time = log.morning_session_time
    set_wake_delta_for_log(log, alarm_time)
    log.save(
        update_fields=[
            "morning_energy",
            "morning_session_completed",
            "morning_session_time",
            "actual_wake_time",
            "wake_delta_minutes",
            "updated_at",
        ]
    )
    log.ritual_streak_day = calculate_ritual_streak(log.user, current_date=log.date)
    log.save(update_fields=["ritual_streak_day", "updated_at"])
    return log


def mark_night_completed(log, mood):
    log.night_mood = mood
    log.night_session_completed = True
    log.night_session_time = timezone.localtime().time().replace(second=0, microsecond=0)
    log.save(
        update_fields=[
            "night_mood",
            "night_session_completed",
            "night_session_time",
            "updated_at",
        ]
    )
    log.ritual_streak_day = calculate_ritual_streak(log.user, current_date=log.date)
    log.save(update_fields=["ritual_streak_day", "updated_at"])
    return log
