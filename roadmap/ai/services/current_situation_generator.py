#=============================================================================
# roadmap/ai/services/current_situation_generator.py
# =============================================================================
import logging
from django.utils import timezone

from ai.services.base_service import BaseAIService
from ai.prompts.personalization.user_context_prompts import UserContextPrompt
from ai.prompts.system_prompts import SystemPrompts
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter

logger = logging.getLogger(__name__)

SITUATION_JOB_TYPE = "situation_analysis"


class CurrentSituationGenerator(BaseAIService):
    """Generates a structured situation analysis from free-form user text."""

    def __init__(self):
        provider = OllamaProvider(
            model="gpt-oss:120b-cloud",
            temperature=0.3,
            max_tokens=2000,
        )
        super().__init__(provider)

        self.user_context_prompt = UserContextPrompt()
        self.system_prompts = SystemPrompts()
        self.response_parser = ResponseParser()
        self.response_formatter = ResponseFormatter()

    def generate(self, raw_data: str, user_age: int, user) -> dict | None:
        """
        Accept raw user input and return a structured situation analysis.

        Returns a dict with keys 'data' and 'job_id' on success, or None on failure.

        FIX 1: 'row_data' → 'input_data' to match the actual model field.
        FIX 2: job_type uses the canonical constant, not a made-up uppercase string.
        FIX 3: Error handling restored — job is marked 'failed' and error is logged
                instead of the except block being commented out.
        FIX 4: started_at / completed_at timestamps tracked properly.
        FIX 5: output_data populated on success so the job record is self-contained.
        """
        print("Starting situation analysis...")
        job, _ = self.create_or_update_job(
            user=user,
            job_type=SITUATION_JOB_TYPE,
            input_data={"raw_data": raw_data, "user_age": user_age},
        )
        print("Job created...")

        # Mark as processing
        job.status = "processing"
        job.started_at = timezone.now()
        job.ai_model_used = self.provider.model
        job.save(update_fields=["status", "started_at", "ai_model_used"])

        try:
            print("Calling AI provider...")
            logger.debug("Calling AI provider for user %s", user.id)

            response = self.provider.generate_response(
                prompt=self.user_context_prompt.format(
                    raw_text=raw_data,
                    age=user_age,
                    strict=False,
                ),
                system_prompt=self.system_prompts.get_current_situation_prompt(),
            )

            parsed_data = self.response_parser.parse_current_situation_response(
                response.content
            )

            # FIX: Persist the result on the job itself (output_data not row_data)
            job.status = "completed"
            job.output_data = parsed_data
            job.raw_ai_response = response.content
            job.user_raw_text = raw_data
            job.completed_at = timezone.now()
            if job.started_at:
                job.processing_time_seconds = (
                    job.completed_at - job.started_at
                ).total_seconds()
            job.save(
                update_fields=[
                    "status",
                    "output_data",
                    "raw_ai_response",
                    "user_raw_text",
                    "completed_at",
                    "processing_time_seconds",
                ]
            )

            print("AI situation analysis completed...")
            logger.info("AI situation analysis completed for user %s", user.id)

            return self.response_formatter.format_success(
                job=job,
                raw_response=response.content,
                parsed_data=parsed_data,
            )

        except Exception as exc:
            # FIX: Always mark the job as failed so stuck-pending jobs are visible
            print("AI situation analysis failed...")
            logger.exception(
                "AI situation analysis failed for user %s: %s", user.id, exc
            )
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])
            return None
