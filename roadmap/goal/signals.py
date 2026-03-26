import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from authentication.models import UserPersonalDetails
from goal.tasks import process_current_situation_task

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=UserPersonalDetails)
def capture_previous_current_situation(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_current_situation = None
        return

    instance._previous_current_situation = (
        UserPersonalDetails.objects.filter(pk=instance.pk)
        .values_list("current_situation", flat=True)
        .first()
    )


@receiver(post_save, sender=UserPersonalDetails)
def trigger_ai_situation_analysis(sender, instance, created, **kwargs):
    current_situation = (instance.current_situation or "").strip()
    if not current_situation:
        return

    previous_situation = getattr(instance, "_previous_current_situation", None)
    if not created and previous_situation == instance.current_situation:
        return

    logger.info("Queueing current-situation analysis for user %s", instance.user_id)
    transaction.on_commit(lambda: process_current_situation_task.delay(instance.pk))
