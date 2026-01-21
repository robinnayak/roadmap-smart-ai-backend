"""
Docstring for roadmap.ai.services.text_extraction

Text extraction services for user personalization, goals, and attributes.
Converts user text into structured JSON format with clean, consistent output.
"""

from typing import Dict, Any
from .base_service import BaseAIService
from ai.prompts.system_prompts import SystemPrompts
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter
import logging
from ai.prompts.base_prompts import BasePrompt

logger = logging.getLogger(__name__)


class GoalAttributeExtractor(BaseAIService):
    """
    Extracts structured information from user-written goals.
    """

    def __init__(self):
        """Initialize the GoalAttributeExtractor."""
        provider = OllamaProvider(
            model="gpt-oss:120b-cloud",
            temperature=0.3,  # Lower temperature for consistent structured output
            max_tokens=2000,
        )
        super().__init__(provider)

        self.response_parser = ResponseParser()
        self.response_formatter = ResponseFormatter()

    def extract_goal_attributes(self, user_input: str, user, goal_id: int) -> Dict[str, Any]:
        """
        Processes raw user text to extract goal attributes.

        Args:
            user_input: The raw text input from the user describing their goal.
            user: The user model instance.

        Returns:
            A dictionary containing the structured goal attributes.
        """
        # Create processing job - unpack the tuple to get just the job object
        try:
            job_result = self.create_job(
                user=user,
                job_type=f"goal_attribute_extraction_{goal_id}",
                row_data={"user_input": user_input},
            )
            print(f"Job result type: {type(job_result)}, value: {job_result}")

            # Extract just the job object from the tuple
            if isinstance(job_result, tuple) and len(job_result) > 0:
                job = job_result[0]  # Get the job object from the tuple
            else:
                job = job_result  # If it's not a tuple, use as is

            print(f"Job created: {job}")  # Debug

            # Get the system prompt for goal attribute extraction
            goal_attribute_context_extraction_prompt = SystemPrompts.get_prompt(
                "goal_attribute_context_extraction"
            )

            # print(f"System prompt: {goal_attribute_context_extraction_prompt}")
            print(f"User input: {user_input}")
            # Generate response from AI
            logger.info(f"Extracting goal attributes for user {user.email}")
            response = self.provider.generate_response(
                prompt=user_input,
                system_prompt=goal_attribute_context_extraction_prompt,
            )

            print(
                f"AI Response Content: {response.content[:500]}..."
            )  # Show first 200 chars

            # Parse the JSON response
            print("==" * 10)
            parsed_data = ResponseParser.parse_current_situation_response(
                response.content
            )
            print(f"Parsed data: {parsed_data}")

            # Update job status - only if job has the expected attributes
            if hasattr(job, "status"):
                job.status = "COMPLETED"
            if hasattr(job, "user_raw_text"):
                job.user_raw_text = user_input
            if hasattr(job, "save"):
                job.save()

            # Format and return success response

            return ResponseFormatter.format_success(
                parsed_data=parsed_data,
                job=job,
                raw_response=response.content,
            )

        except ValueError as ve:
            logger.error(f"ValueError in goal attribute extraction: {str(ve)}")
            return ResponseFormatter.format_error(
                str(ve), "VALUE_ERROR", data={"user_input": user_input}
            )

        except Exception as e:
            logger.error(f"Goal attribute extraction failed: {str(e)}", exc_info=True)

            # Try to update job status if job exists
            if "job" in locals() and hasattr(job, "status"):
                job.status = "FAILED"
                if hasattr(job, "save"):
                    job.save()

            return ResponseFormatter.format_error(
                str(e), "EXTRACTION_FAILED", data={"user_input": user_input}
            )
