"""Centralized long-horizon demo data for Journey Book generation.

This module is intentionally isolated from persistence and database access.
It provides deterministic, realistic sample journey data for previews,
print-ready demo PDFs, and non-production testing.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

START_DATE = date(2024, 7, 1)
TOTAL_DAYS = 450  # Extended from 210 to provide print-realistic long-form content.


DEMO_USER_PROFILE: dict[str, Any] = {
    "id": "demo-user-001",
    "email": "alex.rivera@example.com",
    "name": "Alex Rivera",
    "timezone": "America/New_York",
    "roadmap_start_date": START_DATE,
    "current_situation": (
        "Working full-time in operations while transitioning into analytics, "
        "rebuilding savings, and stabilizing health routines after burnout."
    ),
}

DEMO_GOALS: list[dict[str, Any]] = [
    {
        "id": "goal-career-001",
        "title": "Transition into a junior data analyst role",
        "category": "career",
        "status": "in_progress",
        "deadline": date(2026, 3, 31),
        "start_date": START_DATE,
        "created_at": START_DATE,
    },
    {
        "id": "goal-financial-001",
        "title": "Build and protect a 6-month emergency fund",
        "category": "financial",
        "status": "in_progress",
        "deadline": date(2026, 2, 28),
        "start_date": START_DATE,
        "created_at": START_DATE,
    },
    {
        "id": "goal-personal-001",
        "title": "Journal consistently and improve emotional regulation",
        "category": "personal",
        "status": "in_progress",
        "deadline": date(2025, 12, 31),
        "start_date": START_DATE,
        "created_at": START_DATE,
    },
    {
        "id": "goal-health-001",
        "title": "Rebuild strength and sustain training 4 days/week",
        "category": "health",
        "status": "in_progress",
        "deadline": date(2026, 1, 31),
        "start_date": START_DATE,
        "created_at": START_DATE,
    },
]


def _phase_for_day(day: int) -> str:
    if day <= 30:
        return "momentum"
    if day <= 60:
        return "buildout"
    if day <= 95:
        return "slump"
    if day == 96:
        return "turning_point"
    if day <= 210:
        return "consistency"
    if day <= 330:
        return "compounding"
    return "mastery"


def _sentiment_for_day(day: int, phase: str) -> float:
    if phase == "momentum":
        return round(0.35 + ((day % 11) * 0.045), 3)
    if phase == "buildout":
        return round(0.2 + ((day % 9) * 0.04), 3)
    if phase == "slump":
        return round(-0.62 + ((day % 10) * 0.09), 3)
    if phase == "turning_point":
        return 0.66
    if phase == "consistency":
        return round(0.38 + ((day % 8) * 0.055), 3)
    if phase == "compounding":
        return round(0.48 + ((day % 7) * 0.055), 3)
    return round(0.58 + ((day % 6) * 0.05), 3)


def _sentiment_label(score: float) -> str:
    if score >= 0.45:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "neutral"


def _journal_completed(day: int, phase: str) -> bool:
    weekday = (START_DATE + timedelta(days=day - 1)).weekday()
    if phase == "slump":
        return day % 4 != 0 and weekday != 6
    if phase == "buildout":
        return day % 10 != 0
    if phase == "consistency":
        return day % 19 != 0
    if phase == "compounding":
        return day % 29 != 0
    return True


def _habit_completion_map(day: int, phase: str) -> dict[str, bool]:
    weekday = (START_DATE + timedelta(days=day - 1)).weekday()
    is_weekend = weekday >= 5

    if phase == "momentum":
        return {
            "deep_work_90_min": day % 8 != 0,
            "budget_review": day % 7 != 0,
            "workout_40_min": day % 6 != 0 or is_weekend,
            "evening_reflection": True,
        }
    if phase == "buildout":
        return {
            "deep_work_90_min": day % 6 != 0,
            "budget_review": day % 8 != 0,
            "workout_40_min": day % 5 != 0,
            "evening_reflection": day % 9 != 0,
        }
    if phase == "slump":
        return {
            "deep_work_90_min": day % 2 == 0,
            "budget_review": day % 3 == 0,
            "workout_40_min": day % 4 == 0,
            "evening_reflection": day % 3 != 0,
        }
    if phase == "turning_point":
        return {
            "deep_work_90_min": True,
            "budget_review": True,
            "workout_40_min": True,
            "evening_reflection": True,
        }
    if phase == "consistency":
        return {
            "deep_work_90_min": day % 7 != 0,
            "budget_review": day % 9 != 0,
            "workout_40_min": day % 6 != 0,
            "evening_reflection": True,
        }
    if phase == "compounding":
        return {
            "deep_work_90_min": day % 9 != 0,
            "budget_review": day % 10 != 0,
            "workout_40_min": day % 7 != 0,
            "evening_reflection": True,
        }
    return {
        "deep_work_90_min": day % 11 != 0,
        "budget_review": day % 12 != 0,
        "workout_40_min": day % 8 != 0,
        "evening_reflection": True,
    }


def _short_reflection(day: int, phase: str, completed: bool) -> str:
    if not completed:
        return "Low-energy day. Logging a short check-in to protect momentum."
    if phase == "momentum":
        return "Strong momentum day. Focus and execution were aligned."
    if phase == "buildout":
        return "Solid work with manageable friction."
    if phase == "slump":
        return "Heavy day. Confidence dipped and routines felt fragile."
    if phase == "turning_point":
        return "Turning point. I recommitted to standards over mood."
    if phase == "consistency":
        return "Consistent execution. Fewer negotiations with myself."
    if phase == "compounding":
        return "Compounding phase. Systems are carrying more of the load."
    return "Mastery phase. Quiet confidence is replacing urgency."


def _long_reflection(day: int, phase: str, completed: bool) -> str:
    if not completed:
        return (
            "I skipped the full entry and kept only a short check-in. The day drifted with too "
            "many reactive choices, but I still showed up enough to prevent a full disconnect. "
            "Tomorrow starts with one high-leverage task before anything else."
        )

    if phase == "momentum":
        return (
            "I closed priority tasks early, reviewed spending, and trained before dinner. The key "
            "win is not intensity but repeatability. I can already see how simple structure lowers "
            "decision fatigue and protects progress."
        )
    if phase == "buildout":
        return (
            "Execution was decent but less exciting. I am learning that sustainable growth feels "
            "ordinary most days. Better planning the night before reduced morning chaos and helped "
            "me finish deep work blocks."
        )
    if phase == "slump":
        return (
            "Energy and confidence were low. I procrastinated on demanding tasks and defaulted to "
            "easy wins. The useful part is awareness: I can identify the pattern early and shorten "
            "the recovery window."
        )
    if phase == "turning_point":
        return (
            "I reviewed ninety-plus days of entries and found evidence that I can restart after any "
            "dip. I reduced the daily plan to non-negotiables and committed to consistency over "
            "intensity. This feels like a durable reset."
        )
    if phase == "consistency":
        return (
            "Daily systems are working: focused block, training, money review, reflection. I still "
            "have uneven days, but I recover faster and avoid all-or-nothing thinking. Confidence "
            "feels earned through reps."
        )
    if phase == "compounding":
        return (
            "The second half of this journey is noticeably different. The same routines now generate "
            "better outcomes with less emotional drag. I am spending more time on high-value work "
            "and less time rebuilding after preventable mistakes."
        )
    return (
        "Progress feels quieter and more stable. I am not chasing spikes of motivation; I am relying "
        "on systems, review loops, and clear constraints. This version of discipline feels like "
        "identity, not effort."
    )


def _struggle_note(phase: str) -> str:
    if phase == "slump":
        return "Managing fatigue, avoidance, and self-doubt without abandoning the process."
    if phase in {"buildout", "consistency"}:
        return "Avoiding overcommitment while preserving quality and consistency."
    if phase == "compounding":
        return "Protecting focus from growing responsibilities and context switching."
    return "Balancing ambition across career, finance, personal growth, and health."


def _emotional_state(score: float, phase: str) -> dict[str, str]:
    return {
        "confidence": "high" if score >= 0.5 else "low" if score <= -0.2 else "mixed",
        "stress": "high" if phase == "slump" else "moderate" if phase in {"buildout", "consistency"} else "low",
        "self_talk": (
            "self-critical"
            if phase == "slump"
            else "constructive" if phase in {"turning_point", "consistency", "compounding", "mastery"} else "ambitious"
        ),
    }


def _build_demo_daily_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    running_streak = 0
    longest_streak = 0

    for day in range(1, TOTAL_DAYS + 1):
        entry_date = START_DATE + timedelta(days=day - 1)
        phase = _phase_for_day(day)
        sentiment_score = _sentiment_for_day(day, phase)
        journal_completed = _journal_completed(day, phase)
        habits = _habit_completion_map(day, phase)
        short_text = _short_reflection(day, phase, journal_completed)
        long_text = _long_reflection(day, phase, journal_completed)

        if journal_completed:
            running_streak += 1
            longest_streak = max(longest_streak, running_streak)
        else:
            running_streak = 0

        completed_count = sum(1 for value in habits.values() if value)
        total_count = len(habits)
        week_of_journey = ((day - 1) // 7) + 1
        month_of_journey = ((day - 1) // 30) + 1

        entries.append(
            {
                "id": f"demo-entry-{day:04d}",
                "day_number": day,
                "entry_date": entry_date,
                "phase": phase,
                "journal_completed": journal_completed,
                "reflection_short": short_text,
                "reflection_long": long_text,
                "reflection_raw": f"{short_text} {long_text}".strip(),
                "struggle_raw": _struggle_note(phase),
                "sentiment_score": sentiment_score,
                "sentiment_label": _sentiment_label(sentiment_score),
                "emotional_state": _emotional_state(sentiment_score, phase),
                "habit_completions": habits,
                "habit_summary": {
                    "completed": completed_count,
                    "total": total_count,
                    "completion_rate": round(completed_count / total_count, 2),
                    "missed_habits": [name for name, done in habits.items() if not done],
                },
                "streak_history": {
                    "current_streak": running_streak,
                    "longest_streak_so_far": longest_streak,
                },
                "weekly_context": {
                    "week_of_journey": week_of_journey,
                    "month_of_journey": month_of_journey,
                    "weekday": entry_date.strftime("%A"),
                },
                "tags": [
                    phase,
                    "career_transition",
                    "financial_recovery",
                    "discipline",
                    "turning_point" if phase == "turning_point" else "daily_progress",
                ],
                "total_word_count": len(f"{short_text} {long_text}".split()),
            }
        )

    return entries


DEMO_DAILY_ENTRIES: list[dict[str, Any]] = _build_demo_daily_entries()

DEMO_MILESTONES: list[dict[str, Any]] = [
    {"label": "The First Step", "trigger_type": "first_journal_entry", "achieved_date": START_DATE, "category": "writing"},
    {"label": "One Week In", "trigger_type": "streak_7", "achieved_date": START_DATE + timedelta(days=6), "category": "discipline"},
    {"label": "A Month of Discipline", "trigger_type": "streak_30", "achieved_date": START_DATE + timedelta(days=29), "category": "discipline"},
    {"label": "Savings Streak Opened", "trigger_type": "budget_30_days", "achieved_date": START_DATE + timedelta(days=44), "category": "financial"},
    {"label": "Turning the Corner", "trigger_type": "avg_sentiment_cross_0_3", "achieved_date": START_DATE + timedelta(days=95), "category": "personal"},
    {"label": "50 Stories Written", "trigger_type": "journal_50_entries", "achieved_date": START_DATE + timedelta(days=104), "category": "writing"},
    {"label": "First Portfolio Case Study", "trigger_type": "career_project_1", "achieved_date": START_DATE + timedelta(days=138), "category": "career"},
    {"label": "Century Mark", "trigger_type": "streak_100", "achieved_date": START_DATE + timedelta(days=189), "category": "discipline"},
    {"label": "Half-Year Consistency", "trigger_type": "journey_180_days", "achieved_date": START_DATE + timedelta(days=179), "category": "discipline"},
    {"label": "Emergency Fund 1-Month", "trigger_type": "emergency_fund_1_month", "achieved_date": START_DATE + timedelta(days=210), "category": "financial"},
    {"label": "200 Journal Entries", "trigger_type": "journal_200_entries", "achieved_date": START_DATE + timedelta(days=245), "category": "writing"},
    {"label": "Training Base Restored", "trigger_type": "workout_150_days", "achieved_date": START_DATE + timedelta(days=274), "category": "health"},
    {"label": "Career Interview Milestone", "trigger_type": "career_interview_3", "achieved_date": START_DATE + timedelta(days=318), "category": "career"},
    {"label": "300 Journal Entries", "trigger_type": "journal_300_entries", "achieved_date": START_DATE + timedelta(days=352), "category": "writing"},
    {"label": "Long Horizon Discipline", "trigger_type": "journey_365_days", "achieved_date": START_DATE + timedelta(days=364), "category": "discipline"},
    {"label": "Emergency Fund 3-Month", "trigger_type": "emergency_fund_3_month", "achieved_date": START_DATE + timedelta(days=401), "category": "financial"},
    {"label": "Mastery Window", "trigger_type": "journey_450_days", "achieved_date": START_DATE + timedelta(days=449), "category": "personal"},
]

DEMO_BOOK_CONTENT: dict[str, Any] = {
    "book_type": "complete",
    "chapters": [
        {"chapter_number": 1, "chapter_title": "Who I Was - Day One", "summary": "Clear ambition with early momentum and structured routines.", "entry_range": [1, 60]},
        {"chapter_number": 2, "chapter_title": "The Dip", "summary": "A prolonged slump with missed routines, low confidence, and emotional friction.", "entry_range": [61, 95]},
        {"chapter_number": 3, "chapter_title": "The Turning Point", "summary": "A standards reset around Day 96 that restored directional clarity.", "entry_range": [96, 120]},
        {"chapter_number": 4, "chapter_title": "Compounding Progress", "summary": "Durable habits produce stronger outcomes with less internal resistance.", "entry_range": [121, 330]},
        {"chapter_number": 5, "chapter_title": "Who I Became", "summary": "Long-run consistency transforms confidence, identity, and execution quality.", "entry_range": [331, TOTAL_DAYS]},
    ],
}


def _build_collector_journals(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    journals: list[dict[str, Any]] = []
    for row in entries:
        journals.append(
            {
                "id": row["id"],
                "entry_date": row["entry_date"],
                "reflection_raw": row["reflection_raw"],
                "struggle_raw": row["struggle_raw"],
                "sentiment_score": row["sentiment_score"],
                "sentiment_label": row["sentiment_label"],
                "tags": row["tags"],
                "total_word_count": row["total_word_count"],
            }
        )
    return journals


def _build_streaks(entries: list[dict[str, Any]]) -> dict[str, Any]:
    current = entries[-1]["streak_history"]["current_streak"] if entries else 0
    longest = max((e["streak_history"]["longest_streak_so_far"] for e in entries), default=0)
    last_entry_date = entries[-1]["entry_date"] if entries else None
    return {"current_streak": int(current), "longest_streak": int(longest), "last_entry_date": last_entry_date}


def _build_word_frequencies(entries: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    stop_words = {"the", "and", "that", "with", "from", "this", "have", "were", "will", "into", "over", "after"}

    for entry in entries:
        words = (
            (entry.get("reflection_raw") or "")
            .lower()
            .replace(".", " ")
            .replace(",", " ")
            .replace("-", " ")
            .split()
        )
        for word in words:
            if len(word) < 4 or word in stop_words:
                continue
            counter[word] += 1
    return dict(counter.most_common(120))


def get_demo_journey_data() -> dict[str, Any]:
    """Return centralized Journey Book demo data in sectioned and collector-like forms."""

    primary_goal = DEMO_GOALS[0]
    journals = _build_collector_journals(DEMO_DAILY_ENTRIES)

    return {
        "DEMO_USER_PROFILE": DEMO_USER_PROFILE,
        "DEMO_GOALS": DEMO_GOALS,
        "DEMO_DAILY_ENTRIES": DEMO_DAILY_ENTRIES,
        "DEMO_MILESTONES": DEMO_MILESTONES,
        "DEMO_BOOK_CONTENT": DEMO_BOOK_CONTENT,
        "profile": DEMO_USER_PROFILE,
        "goal": primary_goal,
        "journals": journals,
        "streaks": _build_streaks(DEMO_DAILY_ENTRIES),
        "word_frequencies": _build_word_frequencies(DEMO_DAILY_ENTRIES),
        "derived_milestones": DEMO_MILESTONES,
    }
