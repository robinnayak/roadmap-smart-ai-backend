import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomUser, Profile, NotificationSettings
from routine.system_habits_service import seed_system_habits_for_user

logger = logging.getLogger(__name__)


@receiver(post_save, sender= CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    print("=" * 70)
    print("sender",sender)
    print("instance", instance)
    print("created", created)
    print("Kwargs", kwargs)
    print("=" * 70)
    if created:
        Profile.objects.create(user=instance)
        NotificationSettings.objects.create(user= instance)


@receiver(post_save, sender=CustomUser)
def seed_system_habits_on_user_create(sender, instance, created, **kwargs):
    if created:
        try:
            seed_system_habits_for_user(instance)
        except Exception as exc:
            logger.error("Failed to seed system habits for user %s: %s", instance.id, exc)
