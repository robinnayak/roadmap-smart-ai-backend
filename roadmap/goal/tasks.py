from __future__ import annotations

import logging

from celery import shared_task

from ai.models import AIProcessingJob
from ai.services.current_situation_generator import CurrentSituationGenerator
from authentication.models import UserPersonalDetails
from goal.models import UserCurrentSituationGoal

logger = logging.getLogger(__name__)


@shared_task
def process_current_situation_task(personal_details_id: str) -> None:
    personal_details = (
        UserPersonalDetails.objects.select_related("user")
        .filter(pk=personal_details_id)
        .first()
    )
    if not personal_details:
        logger.warning(
            "Current-situation task skipped because personal details %s no longer exist.",
            personal_details_id,
        )
        return

    current_situation = (personal_details.current_situation or "").strip()
    if not current_situation:
        logger.info(
            "Current-situation task skipped because personal details %s have no content.",
            personal_details_id,
        )
        return

    logger.info(
        "Processing current-situation analysis for user %s via Celery task.",
        personal_details.user_id,
    )

    generator = CurrentSituationGenerator()
    result = generator.generate(
        raw_data=current_situation,
        user_age=personal_details.current_age,
        user=personal_details.user,
    )

    if not result or "data" not in result or "job_id" not in result:
        logger.error(
            "AI generator returned unexpected result for user %s",
            personal_details.user_id,
        )
        return

    structured_data = result["data"]
    job_id = result["job_id"]

    try:
        job = AIProcessingJob.objects.get(id=job_id, user=personal_details.user)
    except AIProcessingJob.DoesNotExist:
        logger.error(
            "AI processing job %s not found for user %s",
            job_id,
            personal_details.user_id,
        )
        return

    defaults = {
        "user_personal_details": personal_details,
        "current_situation": structured_data,
        "current_role": structured_data.get("current_role"),
        "age": structured_data.get("age"),
        "key_skills": structured_data.get("key_skills"),
        "main_goals": structured_data.get("main_goals"),
        "time_availability": structured_data.get("time_availability"),
        "constraints": structured_data.get("constraints"),
        "priority_areas": structured_data.get("priority_areas"),
    }

    _, created_flag = UserCurrentSituationGoal.objects.update_or_create(
        ai_processing_job=job,
        defaults=defaults,
    )
    logger.info(
        "UserCurrentSituationGoal %s for user %s",
        "created" if created_flag else "updated",
        personal_details.user_id,
    )
