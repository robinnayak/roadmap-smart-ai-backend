from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ai.services.churn_reengagement import ChurnReengagementService


class Command(BaseCommand):
    help = "Compute churn risk and orchestrate re-engagement actions for active users."

    def handle(self, *args, **options):
        user_model = get_user_model()
        service = ChurnReengagementService()

        users = user_model.objects.filter(is_active=True).order_by("date_joined")
        processed = 0
        sent = 0
        suppressed = 0
        blocked = 0

        for user in users:
            result = service.process_user(user=user)
            processed += 1
            status = result.get("status")
            if status == "sent":
                sent += 1
            elif status == "suppressed":
                suppressed += 1
            elif status in {"cooldown_blocked", "reengaged_blocked"}:
                blocked += 1

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Churn re-engagement completed. "
                    f"processed={processed} sent={sent} suppressed={suppressed} blocked={blocked}"
                )
            )
        )
