"""
Docstring for roadmap.ai.services.text_extraction

Text extraction services for user personalization, goals, and attributes.
Converts user text into structured JSON format with clean, consistent output.
"""

from typing import Dict, Any
from .base_service import BaseAIService
from ai.prompts.system_prompts import SystemPrompts
from ai.config import get_ollama_model
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter
import logging
from ai.prompts.base_prompts import BasePrompt

logger = logging.getLogger(__name__)

# Must match JOB_TYPE_CHOICES in AIProcessingJob
GOAL_ATTRIBUTES_JOB_TYPE = "goal_attributes"

# Maps primary_category → GoalAttributes field name
CATEGORY_TO_FIELD = {
    "financial": "financial_data",
    "finance": "financial_data",
    "career": "career_data",
    "health": "health_data",
    "fitness": "health_data",
    "wellness": "health_data",
    "nutrition": "health_data",
    "personal": "personal_data",
    "productivity": "personal_data",
}


def resolve_goal_attributes_field(primary_category: str | None) -> str:
    category = (primary_category or "").strip().lower()
    return CATEGORY_TO_FIELD.get(category, "personal_data")


class GoalAttributeExtractor(BaseAIService):
    """
    Extracts structured GoalAttributes from user free-text via AI.

    Uses AIProcessingJob to track every extraction — start, success, failure.
    Uses the model's own mark_completed() / mark_failed() methods instead of
    manually setting status strings to avoid the uppercase/lowercase bug.
    """

    def __init__(self):
        provider = OllamaProvider(
            model=get_ollama_model(),
            temperature=0.3,   # Low temperature → consistent structured JSON
            max_tokens=2000,
        )
        super().__init__(provider)
        self.parser = ResponseParser()
        self.formatter = ResponseFormatter()

    def extract_goal_attributes(
        self,
        user_input: str,
        user,
        goal_id: str,
        primary_category: str = "",
    ) -> dict[str, Any]:
        """
        Extract structured attributes from a free-text goal description.

        Args:
            user_input:        Raw text the user wrote about their goal.
            user:              CustomUser instance (for job ownership).
            goal_id:           Goal UUID string (stored in job metadata).
            primary_category:  Goal's primary_category value (financial/career/
                               health/personal). Used to determine which
                               GoalAttributes field to populate.

        Returns:
            {
                'status': 'success' | 'error',
                'data': {
                    'financial_data': { ... }   # or career_data / health_data / personal_data
                },
                'job_id': '<uuid>'
            }
        """
        # FIX 1: Use create_or_update_job (correct method name) with input_data
        #         (correct field name). job_type matches JOB_TYPE_CHOICES exactly.
        job, _ = self.create_or_update_job(
            user=user,
            job_type=GOAL_ATTRIBUTES_JOB_TYPE,
            input_data={
                "user_input": user_input,
                "goal_id": goal_id,
                "primary_category": primary_category,
            },
        )

        # FIX 2: Use the model method — sets status='processing' + started_at atomically
        job.start_processing()

        try:
            system_prompt = SystemPrompts.get_prompt("goal_attribute_context_extraction")

            logger.info(
                "Extracting goal attributes for user %s, goal %s, category '%s'",
                user.id, goal_id, primary_category,
            )

            response = self.provider.generate_response(
                prompt=user_input,
                system_prompt=system_prompt,
            )

            # FIX 3: Use parse_json, NOT parse_current_situation_response.
            #         Goal attributes have a completely different JSON shape
            #         from the situation analysis response.
            parsed_data = self.parser.parse_json(response.content)

            if not parsed_data:
                raise ValueError("AI returned empty or unparseable JSON for goal attributes.")

            # Wrap the raw extracted data under the correct GoalAttributes field name
            # so the serializer / view can call GoalAttributes.objects.update_or_create
            # directly with the returned dict.
            field_name = resolve_goal_attributes_field(primary_category)
            structured_output = {field_name: parsed_data}

            # FIX 4: Use mark_completed() — handles status, timestamps, output_data,
            #         and processing_time_seconds in one atomic save.
            job.mark_completed(
                output_data=structured_output,
                raw_response=response.content,
                model_used=self.provider.model,
                tokens=response.token_used or 0,
            )

            logger.info("Goal attribute extraction completed for goal %s", goal_id)

            return {
                "status": "success",
                "data": structured_output,
                "job_id": str(job.id),
            }

        except Exception as exc:
            logger.exception(
                "Goal attribute extraction failed for user %s, goal %s: %s",
                user.id, goal_id, exc,
            )
            # FIX 5: Use mark_failed() — handles status, error_message, retry_count,
            #         and processing_time_seconds in one atomic save.
            #         No more 'if "job" in locals()' — job is always defined here
            #         because create_or_update_job runs before start_processing.
            job.mark_failed(error_message=str(exc))

            return {
                "status": "error",
                "message": str(exc),
                "job_id": str(job.id),
            }
