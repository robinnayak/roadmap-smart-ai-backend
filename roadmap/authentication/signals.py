from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomUser, Profile, NotificationSettings


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
        
