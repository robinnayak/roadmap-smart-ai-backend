
import logging
from django.db import transaction
from ai.models import AIProcessingJob

logger = logging.getLogger(__name__)


class BaseAIService:
    """Base class for all AI generation services"""
    
    def __init__(self, provider):
        self.provider = provider
        
    
    def create_or_update_job(self, user, job_type:str, input_data: dict):
        """
        Atomically get-or-create an AIProcessingJob for this user + job_type,
        then update input_data and reset status to 'pending'.

        FIX 1: Uses update_or_create inside a transaction to eliminate the
                race condition that existed with filter().first() + create().
        FIX 2: Field name corrected from 'row_data' → 'input_data'.
        FIX 3: Status uses lowercase to match JOB_STATUS_CHOICES.
        """
        print("Starting job creation...")

        with transaction.atomic():
            job, created = AIProcessingJob.objects.update_or_create(
                user=user, 
                job_type=job_type,
                defaults={
                    "input_data": input_data,
                    "status": "pending",
                    "error_message": "",
                    "progress_percentage": 0,
                },
            )
        
        logger.info(
            "Job %s for user %s (type=%s)",
            "created" if created else "updated",
            user.id,
            job_type,
        )
        print(f"Job {'created' if created else 'updated'} for user {user.id} (type={job_type})")
        return job, created

    def create_job(self, user, job_type: str, input_data: dict, metadata: dict | None = None):
        """
        Create a fresh AIProcessingJob row for each request.
        Use this for long-running operations where frontend polls a specific job id.
        """
        print("Starting fresh job creation...")
        with transaction.atomic():
            job = AIProcessingJob.objects.create(
                user=user,
                job_type=job_type,
                input_data=input_data or {},
                metadata=metadata or {},
                status="pending",
                error_message="",
                progress_percentage=0,
            )
        logger.info("Fresh job created for user %s (type=%s)", user.id, job_type)
        print(f"Fresh job created for user {user.id} (type={job_type})")
        return job
            
        
        
