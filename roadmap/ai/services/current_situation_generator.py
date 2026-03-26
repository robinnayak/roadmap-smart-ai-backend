#=============================================================================
# roadmap/ai/services/current_situation_generator.py
# =============================================================================
import logging
from django.core.exceptions import ImproperlyConfigured

from ai.services.base_service import BaseAIService
from ai.prompts.personalization.user_context_prompts import UserContextPrompt
from ai.prompts.system_prompts import SystemPrompts
from ai.config import get_model_for_task
from ai.providers.router import create_routed_provider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter

logger = logging.getLogger(__name__)

SITUATION_JOB_TYPE = "situation_analysis"


class CurrentSituationGenerationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "situation_analysis_failed",
        http_status: int = 502,
        job_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.job_id = job_id


class CurrentSituationGenerator(BaseAIService):
    """Generates a structured situation analysis from free-form user text."""

    def __init__(self):
        provider = create_routed_provider(
            task_name="current_situation",
            model=get_model_for_task("current_situation"),
            temperature=0.3,
            max_tokens=2000,
        )
        super().__init__(provider)

        self.user_context_prompt = UserContextPrompt()
        self.system_prompts = SystemPrompts()
        self.response_parser = ResponseParser()
        self.response_formatter = ResponseFormatter()

    def generate(self, raw_data: str, user_age: int, user) -> dict:
        """
        Accept raw user input and return a structured situation analysis.

        Returns a dict with keys 'data' and 'job_id' on success.

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

        job.user_raw_text = raw_data
        job.ai_model_used = self.provider.model
        job.save(update_fields=["user_raw_text", "ai_model_used", "updated_at"])
        job.start_processing()

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

            job.mark_completed(
                output_data=parsed_data,
                raw_response=response.content,
                model_used=self.provider.model,
                tokens=response.token_used or 0,
            )

            print("AI situation analysis completed...")
            logger.info("AI situation analysis completed for user %s", user.id)

            return self.response_formatter.format_success(
                job=job,
                raw_response=response.content,
                parsed_data=parsed_data,
            )

        except Exception as exc:
            print("AI situation analysis failed...")
            logger.exception(
                "AI situation analysis failed for user %s: %s", user.id, exc
            )
            job.mark_failed(error_message=str(exc))

            if isinstance(exc, ImproperlyConfigured):
                raise CurrentSituationGenerationError(
                    str(exc),
                    code="ai_provider_unavailable",
                    http_status=503,
                    job_id=str(job.id),
                ) from exc

            raise CurrentSituationGenerationError(
                str(exc),
                code="situation_analysis_failed",
                http_status=502,
                job_id=str(job.id),
            ) from exc
