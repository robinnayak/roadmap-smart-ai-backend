from django.core.management.base import BaseCommand

from authentication.models import CustomUser
from routine.system_habits_service import seed_system_habits_for_user


class Command(BaseCommand):
    help = "Seed system habits for all existing users who do not have them yet."

    def handle(self, *args, **kwargs):
        users = CustomUser.objects.all()
        total_created = 0

        for user in users:
            count = seed_system_habits_for_user(user)
            if count > 0:
                self.stdout.write(f"  Seeded {count} habits for user {user.id}")
            total_created += count

        self.stdout.write(
            self.style.SUCCESS(f"Done. Total system habits created: {total_created}")
        )
