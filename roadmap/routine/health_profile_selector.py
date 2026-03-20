from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from routine.models import HealthProfile


def get_active_profile(user):
    profile = (
        HealthProfile.objects.filter(user=user, is_active=True)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if profile:
        return profile
    return (
        HealthProfile.objects.filter(user=user)
        .order_by("-updated_at", "-created_at")
        .first()
    )


def get_effective_profile(user, profile_id=None, require_existing=False):
    if profile_id:
        profile = HealthProfile.objects.filter(user=user, id=profile_id).first()
        if profile is None and require_existing:
            raise ValidationError("Health profile not found.")
        return profile

    profile = get_active_profile(user)
    if profile is None and require_existing:
        raise ValidationError("Complete your health profile first.")
    return profile


@transaction.atomic
def activate_profile(*, user, profile):
    target = HealthProfile.objects.select_for_update().filter(user=user, id=profile.id).first()
    if target is None:
        raise ValidationError("Health profile not found.")
    HealthProfile.objects.filter(user=user, is_active=True).exclude(id=target.id).update(is_active=False)
    if not target.is_active:
        target.is_active = True
        target.save(update_fields=["is_active", "updated_at"])
    return target
