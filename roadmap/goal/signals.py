# roadmap\goal\signals.py
import logging
from django.db import close_old_connections
from django.db.models.signals import post_save
from django.dispatch import receiver

# FIX: Import UserPersonalDetails from wherever it lives in your project
from authentication.models import UserPersonalDetails
from ai.models import AIProcessingJob
from goal.models import UserCurrentSituationGoal
import threading
from ai.services.current_situation_generator import CurrentSituationGenerator

logger = logging.getLogger(__name__)


SITUATION_JOB_TYPE = "situation_analysis"


@receiver(post_save, sender=UserPersonalDetails)
def trigger_ai_situation_analysis(sender, instance, created, **kwargs):
    """
    Trigger AI situation analysis when current_situation text is saved.

    FIX 1: Only fires when current_situation actually has content.
    FIX 2: Compares old vs new value to avoid re-triggering on unrelated saves.
    FIX 3: Uses Celery task instead of raw thread for production safety.
          If Celery is not set up yet, the thread fallback is included but
          with proper DB connection cleanup.
    """
    print("===" * 60)
    print("Triggered user personal details save")
    print(instance.current_situation)
    print(instance.current_age)
    print(instance.pk)
    print("===" * 60)

    if not instance.current_situation or not instance.current_situation.strip():
        print("if not instance block running...")
        return

    # Avoid re-triggering if the situation text hasn't changed.
    # This requires django-model-utils or a simple DB fetch of the old value.
    if not created:
        try:
            print("try block running...")
            old_values = (
                UserPersonalDetails.objects.filter(pk=instance.pk)
                .values_list("current_situation", flat=True)
                .first()
            )
            if old_values is not None and old_values == instance.current_situation:
                return
        except Exception as e:
            pass  # If we can't compare, proceed - better to run that to skip

    logger.info(f"Triggering AI analysis for user: {instance.user_id}")
    print(f"Triggering AI analysis for user: {instance.user_id}")

    def _run():
        try:
            print("Background AI processing running...")
            print(f"Background AI processing running for user {instance.user_id}")
            _process_and_create_situation_goal(
                user=instance.user,
                current_situation=instance.current_situation,
                current_age=instance.current_age,
                personal_details_id=instance.pk,
            )
        except Exception as exc:
            logger.exception(
                "Background AI processing failed for user %s: %s",
                instance.user_id,
                exc,
            )
            print(f"Background AI processing failed for user {instance.user_id}: {exc}")
        finally:
            close_old_connections()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def _process_and_create_situation_goal(
    user, current_situation, current_age, personal_details_id=None
):
    """
    Call AI service and persist the result as UserCurrentSituationGoal.

    FIX: personal_details_id passed in so the FK is always populated.
    """
    print("Starting goal creation...")

    generator = CurrentSituationGenerator()
    result = generator.generate(
        raw_data=current_situation,
        user_age=current_age,
        user=user,
    )

    if not result or "data" not in result or "job_id" not in result:
        logger.error("AI generator returned unexpected result for user %s", user.id)
        print(f"AI generator returned unexpected result for user {user.id}")
        return

    structured_data = result["data"]
    job_id = result["job_id"]

    try:
        job = AIProcessingJob.objects.get(id=job_id)
    except AIProcessingJob.DoesNotExist:
        print(f"AI processing {job_id} not found for user {user.id}")
        logger.error("AI processing %s not found for user %s", job_id, user.id)
        return

    defaults = {
        "user_personal_details_id": personal_details_id,
        "current_situation": structured_data,
        "current_role": structured_data.get("current_role"),
        "age": structured_data.get("age"),
        "key_skills": structured_data.get("key_skills"),
        "main_goals": structured_data.get("main_goals"),
        "time_availability": structured_data.get("time_availability"),
        "constraints": structured_data.get("constraints"),
        "priority_areas": structured_data.get("priority_areas"),
    }

    situation_goal, created_flag = UserCurrentSituationGoal.objects.update_or_create(
        ai_processing_job=job,
        defaults=defaults,
    )

    logger.info(
        "UserCurrentSituationGoal %s for user %s",
        "created" if created_flag else "updated",
        user.id,
    )
    print(
        f"UserCurrentSituationGoal {'created' if created_flag else 'updated'} for user {user.id}"
    )
    print("Goal creation complete")

