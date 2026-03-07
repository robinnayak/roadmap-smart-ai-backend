from __future__ import annotations

from datetime import datetime, time
from statistics import median
from zoneinfo import ZoneInfo

from django.utils import timezone

from authentication.models import Profile
from routine.models import WakeBaselineState, WakeInteraction

DEFAULT_TIMEZONE = "UTC"
WAKE_WINDOW_DAYS = 7
MIN_VALID_SAMPLES = 4
OUTLIER_THRESHOLD_MINUTES = 180
BASELINE_DEVIATION_THRESHOLD_MINUTES = 45
BASELINE_DEVIATION_TRIGGER_DAYS = 5


def _safe_zoneinfo(timezone_name: str | None) -> ZoneInfo:
    candidate = (timezone_name or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(candidate)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def resolve_user_timezone(user, header_timezone: str | None = None) -> str:
    if header_timezone:
        header_timezone = header_timezone.strip()
        if header_timezone:
            try:
                ZoneInfo(header_timezone)
                return header_timezone
            except Exception:
                pass

    profile = Profile.objects.filter(user=user).first()
    profile_tz = getattr(profile, "timezone", "") or DEFAULT_TIMEZONE
    try:
        ZoneInfo(profile_tz)
        return profile_tz
    except Exception:
        return DEFAULT_TIMEZONE


def _to_local_minutes(value: datetime, timezone_name: str) -> int:
    zone = _safe_zoneinfo(timezone_name)
    local_value = value.astimezone(zone)
    return (local_value.hour * 60) + local_value.minute


def _minutes_to_time(value: int) -> time:
    value = int(max(0, min(1439, value)))
    return time(hour=value // 60, minute=value % 60)


def _build_baseline_metadata(state: WakeBaselineState | None, *, fallback_reason: str = "") -> dict:
    if not state:
        return {
            "is_available": False,
            "baseline_minutes": None,
            "baseline_time": None,
            "timezone": DEFAULT_TIMEZONE,
            "last_update_reason": fallback_reason,
            "sample_count": 0,
            "valid_sample_count": 0,
            "default_slot": "afternoon",
        }

    baseline_minutes = state.baseline_minutes
    default_slot = "afternoon"
    if baseline_minutes is not None:
        if baseline_minutes < 12 * 60:
            default_slot = "morning"
        elif baseline_minutes < 18 * 60:
            default_slot = "afternoon"
        else:
            default_slot = "evening"

    return {
        "is_available": baseline_minutes is not None,
        "baseline_minutes": baseline_minutes,
        "baseline_time": state.baseline_time.isoformat() if state.baseline_time else None,
        "timezone": state.baseline_timezone,
        "last_update_reason": state.last_update_reason or fallback_reason,
        "sample_count": state.last_sample_count,
        "valid_sample_count": state.last_valid_sample_count,
        "default_slot": default_slot,
    }


def sync_wake_baseline_for_user(user) -> dict:
    state, _ = WakeBaselineState.objects.get_or_create(
        user=user,
        defaults={"baseline_timezone": DEFAULT_TIMEZONE},
    )
    recent_interactions = list(
        WakeInteraction.objects.filter(user=user)
        .order_by("-local_date", "-first_interaction_at")[:WAKE_WINDOW_DAYS]
    )
    sample_count = len(recent_interactions)
    if sample_count < MIN_VALID_SAMPLES:
        state.last_computed_at = timezone.now()
        state.last_sample_count = sample_count
        state.last_valid_sample_count = 0
        state.last_update_reason = "insufficient_samples"
        state.metadata = {
            "window_days": WAKE_WINDOW_DAYS,
            "required_samples": MIN_VALID_SAMPLES,
            "deviation_threshold_minutes": BASELINE_DEVIATION_THRESHOLD_MINUTES,
        }
        state.save(
            update_fields=[
                "last_computed_at",
                "last_sample_count",
                "last_valid_sample_count",
                "last_update_reason",
                "metadata",
                "updated_at",
            ]
        )
        return _build_baseline_metadata(state)

    minute_samples = []
    for item in recent_interactions:
        minute_samples.append(
            {
                "local_date": item.local_date.isoformat(),
                "minutes": _to_local_minutes(item.first_interaction_at, item.timezone_name),
                "timezone": item.timezone_name,
            }
        )

    sample_median = int(median(entry["minutes"] for entry in minute_samples))
    valid_samples = [
        entry
        for entry in minute_samples
        if abs(entry["minutes"] - sample_median) <= OUTLIER_THRESHOLD_MINUTES
    ]
    valid_sample_count = len(valid_samples)
    if valid_sample_count < MIN_VALID_SAMPLES:
        state.last_computed_at = timezone.now()
        state.last_sample_count = sample_count
        state.last_valid_sample_count = valid_sample_count
        state.last_update_reason = "insufficient_valid_samples"
        state.metadata = {
            "window_days": WAKE_WINDOW_DAYS,
            "median_minutes": sample_median,
            "outlier_threshold_minutes": OUTLIER_THRESHOLD_MINUTES,
            "valid_days": [entry["local_date"] for entry in valid_samples],
        }
        state.save(
            update_fields=[
                "last_computed_at",
                "last_sample_count",
                "last_valid_sample_count",
                "last_update_reason",
                "metadata",
                "updated_at",
            ]
        )
        return _build_baseline_metadata(state)

    candidate_minutes = int(round(sum(entry["minutes"] for entry in valid_samples) / valid_sample_count))
    candidate_timezone = valid_samples[0]["timezone"]
    update_reason = "computed_no_change"
    has_baseline = state.baseline_minutes is not None
    baseline_changed = False

    if not has_baseline:
        baseline_changed = True
        update_reason = "initial_inference"
    elif valid_sample_count >= WAKE_WINDOW_DAYS:
        deviation_count = sum(
            1
            for entry in valid_samples[:WAKE_WINDOW_DAYS]
            if abs(entry["minutes"] - int(state.baseline_minutes)) >= BASELINE_DEVIATION_THRESHOLD_MINUTES
        )
        if deviation_count >= BASELINE_DEVIATION_TRIGGER_DAYS:
            baseline_changed = True
            update_reason = "behavior_shift_5_of_7"
        else:
            update_reason = "deviation_below_threshold"
    else:
        update_reason = "insufficient_window_for_shift_check"

    if baseline_changed:
        state.baseline_minutes = candidate_minutes
        state.baseline_time = _minutes_to_time(candidate_minutes)
        state.baseline_timezone = candidate_timezone or DEFAULT_TIMEZONE

    state.last_computed_at = timezone.now()
    state.last_sample_count = sample_count
    state.last_valid_sample_count = valid_sample_count
    state.last_update_reason = update_reason
    state.metadata = {
        "window_days": WAKE_WINDOW_DAYS,
        "median_minutes": sample_median,
        "candidate_minutes": candidate_minutes,
        "outlier_threshold_minutes": OUTLIER_THRESHOLD_MINUTES,
        "deviation_threshold_minutes": BASELINE_DEVIATION_THRESHOLD_MINUTES,
        "valid_days": [entry["local_date"] for entry in valid_samples],
    }
    state.save()

    return _build_baseline_metadata(state)


def record_first_interaction_for_request(*, user, request_path: str, request_method: str, header_timezone: str | None = None):
    now = timezone.now()
    timezone_name = resolve_user_timezone(user=user, header_timezone=header_timezone)
    zone = _safe_zoneinfo(timezone_name)
    local_date = now.astimezone(zone).date()

    interaction, created = WakeInteraction.objects.get_or_create(
        user=user,
        local_date=local_date,
        defaults={
            "first_interaction_at": now,
            "timezone_name": timezone_name,
            "source_path": (request_path or "")[:255],
            "source_method": (request_method or "")[:10].upper(),
        },
    )

    if not created and now < interaction.first_interaction_at:
        interaction.first_interaction_at = now
        interaction.timezone_name = timezone_name
        interaction.source_path = (request_path or "")[:255]
        interaction.source_method = (request_method or "")[:10].upper()
        interaction.save(
            update_fields=[
                "first_interaction_at",
                "timezone_name",
                "source_path",
                "source_method",
                "updated_at",
            ]
        )

    return sync_wake_baseline_for_user(user=user)


def get_wake_baseline_metadata(user) -> dict:
    state = WakeBaselineState.objects.filter(user=user).first()
    if not state:
        return _build_baseline_metadata(None, fallback_reason="not_initialized")
    return _build_baseline_metadata(state)
