#==============================================================================
# roadmap/ai/services/daily_routine_generator.py
# ==============================================================================
"""
Generates ONLY the daily motivation message and mantra via AI.
Task selection is handled by routine/services.py using deterministic DB queries —
there's no reason to use AI for picking which tasks to show today.
"""
import logging
from datetime import date

from ai.services.base_service import BaseAIService
from ai.config import get_ollama_model
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter
from ai.prompts.DailyRoutineGeneratorPrompts import DailyRoutineGeneratorPrompts

logger = logging.getLogger(__name__)

ROUTINE_JOB_TYPE = "motivation_generation"


class DailyRoutineGenerator(BaseAIService):
    """
    Generates personalised daily motivation + mantra.

    Scope is deliberately narrow:
      - Input:  user context, today's tasks/habits, target date
      - Output: { motivation: str, mantra: str }

    Task selection is NOT done here — that belongs in routine/services.py
    where it can be tested without an AI provider.
    """

    def __init__(self):
        provider = OllamaProvider(
            model=get_ollama_model(),
            temperature=0.7,   # Higher temp is fine for creative motivation text
            max_tokens=500,    # Motivation + mantra don't need 3000 tokens
        )
        super().__init__(provider)
        self.parser  = ResponseParser()
        self.formatter = ResponseFormatter()
        self.prompts = DailyRoutineGeneratorPrompts()

    def generate_motivation_and_mantra(
        self,
        user_context: dict,
        goal_tasks: list,
        habits: list,
        events: list | None,
        target_date: date,
        user=None,
    ) -> dict:
        """
        Generate a personalised motivation message and short daily mantra.

        Args:
            user_context:  Dict from _get_user_context() — role, skills, goals.
            goal_tasks:    List of Task model instances scheduled for today.
            habits:        List of HabitTracker instances for today.
            target_date:   The date being planned.
            user:          CustomUser instance. If provided, creates an AIProcessingJob
                           so the call is tracked. Optional to avoid breaking existing
                           callers that don't pass user.

        Returns:
            {
                'status': 'success' | 'error',
                'data': { 'motivation': '...', 'mantra': '...' }
            }
        """
        job = None
        if user:
            job, _ = self.create_or_update_job(
                user=user,
                job_type=ROUTINE_JOB_TYPE,
                input_data={
                    "target_date":   str(target_date),
                    "task_count":    len(goal_tasks),
                    "habit_count":   len(habits),
                    "event_count":   len(events or []),
                },
            )
            job.start_processing()

        try:
            # Combine summarized goal tasks and habits for motivation prompt
            combined_tasks = (
                self._summarise_tasks(goal_tasks)
                + self._summarise_habits(habits)
                + self._summarise_events(events or [])
            )
            
            prompt = self.prompts.get_motivation_prompt(
                user_context=user_context,
                tasks=combined_tasks,
            )

            system_prompt = (
                "You are a motivational coach. "
                "Write a short, personal daily motivation message and a one-line mantra "
                "based on the user's goals and today's tasks. "
                "Respond with valid JSON only: "
                '{"motivation": "...", "mantra": "..."}'
            )

            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt,
            )

            parsed = self.parser.parse_json(response.content)

            if not parsed or "motivation" not in parsed:
                raise ValueError("AI returned unexpected structure for motivation")

            if job:
                job.mark_completed(
                    output_data=parsed,
                    raw_response=response.content,
                    model_used=self.provider.model,
                )

            logger.info("Motivation generated for %s", target_date)
            return {"status": "success", "data": parsed}

        except Exception as exc:
            logger.exception("Motivation generation failed for %s: %s", target_date, exc)
            if job:
                job.mark_failed(error_message=str(exc))
            return {"status": "error", "message": str(exc)}

    # -------------------------------------------------------------------------
    # Private helpers — only format what the prompt actually needs
    # -------------------------------------------------------------------------

    @staticmethod
    def _summarise_tasks(tasks: list) -> list[dict]:
        """
        Return a minimal summary of each task for the prompt.
        FIX: Uses select_related data already in memory — no extra DB queries.
        """
        result = []
        for task in tasks:
            try:
                result.append({
                    "title":    task.title,
                    "goal":     task.subgoal.milestone.goal.title,
                    "category": task.subgoal.milestone.goal.primary_category,
                    "priority": task.priority,
                    "minutes":  task.estimated_duration_minutes,
                })
            except AttributeError:
                # Defensive: if select_related wasn't used, skip rather than crash
                result.append({"title": task.title})
        return result

    @staticmethod
    def _summarise_habits(habits: list) -> list[dict]:
        """
        Return a minimal summary of each habit for the prompt.
        FIX: No longer references habit.category which doesn't exist on the model.
        """
        return [
            {
                "name":    habit.name,
                "minutes": habit.estimated_minutes,
                "priority": habit.priority,
            }
            for habit in habits
        ]

    @staticmethod
    def _summarise_events(events: list) -> list[dict]:
        """Return a minimal summary of each event occurrence for the prompt."""
        result = []
        for event in events:
            result.append(
                {
                    "title": event.get("title", ""),
                    "type": event.get("event_type", ""),
                    "minutes": event.get("duration_minutes", 0),
                    "constraint_mode": event.get("constraint_mode", "hard"),
                    "time_slot": event.get("time_slot"),
                }
            )
        return result

