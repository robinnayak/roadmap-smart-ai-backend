"""
System habit seeding service.
Seeds the 7 compulsory system habits for a given user.
Safe to call multiple times - skips habits that already exist for the user.
"""

import json
from pathlib import Path

from routine.models import HabitTracker

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "system_habits.json"

BACKFILL_FIELDS = ("description", "reason_body", "why_important")


def _backfill_habit_from_fixture(habit, habit_data) -> bool:
    update_fields = []
    for field_name in BACKFILL_FIELDS:
        current_value = getattr(habit, field_name, "")
        fixture_value = habit_data.get(field_name, "")
        if current_value:
            continue
        if not fixture_value:
            continue
        setattr(habit, field_name, fixture_value)
        update_fields.append(field_name)

    if not update_fields:
        return False

    habit.save(update_fields=[*update_fields, "updated_at"])
    return True


def backfill_system_habit_guidance_for_user(user) -> int:
    """
    Fill blank guidance fields on already-existing system habits.
    Does not create missing habits and does not overwrite non-blank values.
    """
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fixture_file:
        system_habits = json.load(fixture_file)

    updated_count = 0
    for habit_data in system_habits:
        habit = HabitTracker.objects.filter(
            user=user,
            name=habit_data["name"],
            is_system=True,
        ).first()
        if not habit:
            continue
        if _backfill_habit_from_fixture(habit, habit_data):
            updated_count += 1

    return updated_count


def seed_system_habits_for_user(user) -> int:
    """
    Seeds system habits for a user.
    Returns the count of newly created habits (0 if already seeded).
    """
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fixture_file:
        system_habits = json.load(fixture_file)

    created_count = 0

    for habit_data in system_habits:
        habit, created = HabitTracker.objects.get_or_create(
            user=user,
            name=habit_data["name"],
            is_system=True,
            defaults=habit_data,
        )
        if created:
            created_count += 1
            continue

        _backfill_habit_from_fixture(habit, habit_data)

    return created_count
