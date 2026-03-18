"""
System habit seeding service.
Seeds the 7 compulsory system habits for a given user.
Safe to call multiple times - skips habits that already exist for the user.
"""

import json
from pathlib import Path

from routine.models import HabitTracker

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "system_habits.json"


def seed_system_habits_for_user(user) -> int:
    """
    Seeds system habits for a user.
    Returns the count of newly created habits (0 if already seeded).
    """
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fixture_file:
        system_habits = json.load(fixture_file)

    created_count = 0

    for habit_data in system_habits:
        _, created = HabitTracker.objects.get_or_create(
            user=user,
            name=habit_data["name"],
            is_system=True,
            defaults=habit_data,
        )
        if created:
            created_count += 1

    return created_count
