from ai.services.base_service import BaseAIService
from ai.config import get_hierarchy_model
from ai.providers.router import create_routed_provider
from ai.utils.parsers import ResponseParser, MilestoneParser
from ai.utils.formatters import MileStoneFormatter
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from datetime import timedelta
from ai.prompts.GoalHierarchyGeneratorPrompts import GoalHierarchyGeneratorPrompts
from ai.utils.validators import OutputValidator
import json
import logging
from typing import Any
from datetime import datetime
import math
import re
from ai.models import AIProcessingJob


logger = logging.getLogger(__name__)

#Must match JOB_TYPE_CHOICES in AIProcessingJob
HIERARCHY_JOB_TYPE = "milestone_generation"

# Generation limits — change here, nowhere else
# MIN_MONTHS = 1
# MAX_MONTHS = 24                 # Raised from 12; supports 23-month trading plan
# DEFAULT_MONTHS = 6
# MAX_MILESTONES = 12
# MAX_SUBGOALS_PER_MILESTONE = 4
# MAX_TASKS_PER_SUBGOAL = 7

# ================================================
# GOAL HIERARCHY GENERATION LIMITS
# ================================================

# ---------- MONTH SETTINGS (Controls timeline) ----------
MIN_MONTHS = 1        # Minimum months allowed
HARD_MAX_MONTHS = 2   # Temporary production guardrail while LLM capacity is constrained
MAX_MONTHS = min(int(os.getenv("HIERARCHY_MAX_MONTHS", "2")), HARD_MAX_MONTHS)
DEFAULT_MONTHS = 2    # Fallback if dates missing

# ---------- MILESTONE SETTINGS (1 per month) ----------
MAX_MILESTONES = 6    # Safety cap - keeps first X milestones

# ---------- SUBGOAL SETTINGS (4 per milestone = weekly) ----------
MAX_SUBGOALS_PER_MILESTONE = int(os.getenv("HIERARCHY_MAX_SUBGOALS_PER_MILESTONE", "3"))

# ---------- TASK SETTINGS (7 per subgoal = daily) ----------
MAX_TASKS_PER_SUBGOAL = int(os.getenv("HIERARCHY_MAX_TASKS_PER_SUBGOAL", "5"))

# ================================================
# TESTING MODE (⚠️ DISABLE IN PRODUCTION)
# ================================================
TESTING_MODE = True     # True = mock data (fast), False = real AI (slow)
TESTING_DELAY = 0.2     # Simulated delay in seconds

FALLBACK_TASK_ITEM_TYPE_BY_CATEGORY = {
    "fitness": "physical",
    "health": "physical",
    "nutrition": "habit",
    "wellness": "habit",
    "spiritual": "ritual",
    "digital_habits": "habit",
}

class GoalHierarchyGenerator(BaseAIService):
    """
    Generates a complete goal hierarchy from a goal_data dict.

    Flow: goal_data → Milestones (monthly) → SubGoals (weekly) → Tasks (daily)

    FIX: Now creates an AIProcessingJob for every hierarchy run so progress
         and failures are visible in the admin / logs. Uses the model's own
         start_processing(), update_progress(), mark_completed(), mark_failed()
         methods rather than manually setting status strings.

    All public methods accept and return plain dicts.
    The view layer (CreateGoalWithHierarchyAPIView) is responsible for
    persisting the result to Milestone / SubGoal / Task models.
    """

    def __init__(self):
        provider = create_routed_provider(
            task_name="goal_hierarchy",
            model=get_hierarchy_model(),
            temperature=0.15,
            max_tokens=int(os.getenv("HIERARCHY_MAX_TOKENS", "2400")),
        )
        super().__init__(provider)
        self.max_task_workers = max(1, int(os.getenv("HIERARCHY_TASK_WORKERS", "1")))
        self.milestone_parser = MilestoneParser()
        self.parser = ResponseParser()
        self.formatter = MileStoneFormatter()
        self.prompts = GoalHierarchyGeneratorPrompts()

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    def generate_complete_hierarchy(
        self,
        goal_data: dict,
        user,
        user_context: dict | None = None,
        existing_job_id: str | None = None,
        mark_job_completed: bool = True,
    ) -> dict[str, Any]:
        """
        Generate a complete hierarchy for a goal and track it as a job.

        Args:
            goal_data:     Dict — title, description, why_it_matters,
                           primary_category, start_date, target_date,
                           impact_dimensions.
            user:          CustomUser instance (for job ownership).
            user_context:  Optional — current_role, key_skills, constraints,
                           etc. from UserCurrentSituationGoal. Personalises output.

        Returns:
            {
                'status': 'success' | 'error',
                'data': {
                    'milestones': [
                        {
                            'milestone_data': { ... },
                            'subgoals': [
                                {
                                    'subgoal_data': { ... },
                                    'tasks': [ { ... }, ... ]
                                },
                                ...                          # up to 4
                            ]
                        },
                        ...                                  # up to MAX_MILESTONES
                    ],
                    'stats': {
                        'milestones_total': int,
                        'subgoals_total':   int,
                        'tasks_total':      int,
                    }
                },
                'job_id': '<uuid>',
                'message': '...'
            }
        """
        logger.info("Starting hierarchy generation for goal: %s", goal_data.get("title"))

        # FIX: Create a tracking job for the full hierarchy run.
        #      job_type='milestone_generation' matches JOB_TYPE_CHOICES.
        

        
        if existing_job_id:
            job = AIProcessingJob.objects.get(
                id=existing_job_id,
                user=user,
                job_type=HIERARCHY_JOB_TYPE,
            )
            job.input_data = {
                "goal_id": goal_data.get("id"),
                "goal_title": goal_data.get("title"),
                "primary_category": goal_data.get("primary_category"),
                "target_date": str(goal_data.get("target_date", "")),
                "user_context": user_context or {},
            }
            job.metadata = {
                **(job.metadata or {}),
                "goal_id": str(goal_data.get("id", "")),
                "progress_message": "Preparing hierarchy generation...",
            }
            job.status = "pending"
            job.error_message = ""
            job.progress_percentage = 0
            job.save(
                update_fields=[
                    "input_data",
                    "metadata",
                    "status",
                    "error_message",
                    "progress_percentage",
                    "updated_at",
                ]
            )
        else:
            job = self.create_job(
                user=user,
                job_type=HIERARCHY_JOB_TYPE,
                input_data={
                    "goal_id": goal_data.get("id"),
                    "goal_title": goal_data.get("title"),
                    "primary_category": goal_data.get("primary_category"),
                    "target_date": str(goal_data.get("target_date", "")),
                    "user_context": user_context or {},
                },
                metadata={
                    "goal_id": str(goal_data.get("id", "")),
                    "progress_message": "Preparing hierarchy generation...",
                },
            )
        job.start_processing()

        try:
            # Step 1 — Milestones (10% progress marker)
            milestones_result = self._generate_milestones(goal_data, user_context)
            if milestones_result.get("status") != "success":
                job.mark_failed(
                    f"Milestone generation failed: {milestones_result.get('message')}"
                )
                return {**milestones_result, "job_id": str(job.id)}

            milestones_list = milestones_result["data"]["milestones"][:MAX_MILESTONES]
            logger.info("Generated %d milestones", len(milestones_list))
            job.update_progress(10, f"Generated {len(milestones_list)} milestones")

            # Step 2 — SubGoals + Tasks for each milestone
            all_milestones_data = []
            total_subgoals = 0
            total_tasks = 0
            partial_failures = []

            for m_idx, milestone_dict in enumerate(milestones_list, 1):
                logger.info(
                    "Processing milestone %d/%d: %s",
                    m_idx, len(milestones_list), milestone_dict.get("title", "?"),
                )

                # Generate subgoals for this milestone
                subgoals_result = self._generate_subgoals(milestone_dict, goal_data)
                if subgoals_result.get("status") != "success":
                    generation_error = {
                        "stage": "subgoal_generation",
                        "message": subgoals_result.get("message", "Subgoal generation failed."),
                        "milestone_title": milestone_dict.get("title", ""),
                        "milestone_index": m_idx,
                    }
                    logger.warning(
                        "Milestone %d — subgoal generation failed, keeping milestone with no subgoals",
                        m_idx,
                    )
                    all_milestones_data.append({
                        "milestone_data": milestone_dict,
                        "subgoals": [],
                        "generation_error": generation_error,
                    })
                    partial_failures.append(generation_error)
                    continue

                subgoals_list = subgoals_result["data"]["subgoals"][:MAX_SUBGOALS_PER_MILESTONE]
                milestone_entry = {"milestone_data": milestone_dict, "subgoals": []}

                # Generate tasks for each subgoal
                task_results_by_index: dict[int, dict] = {}
                with ThreadPoolExecutor(max_workers=min(self.max_task_workers, max(1, len(subgoals_list)))) as executor:
                    future_map = {
                        executor.submit(self._generate_tasks, subgoal_dict, milestone_dict, goal_data): sg_idx
                        for sg_idx, subgoal_dict in enumerate(subgoals_list, 1)
                    }
                    for future in as_completed(future_map):
                        sg_idx = future_map[future]
                        try:
                            task_results_by_index[sg_idx] = future.result()
                        except Exception as exc:
                            logger.exception("Task generation failed for subgoal %d: %s", sg_idx, exc)
                            task_results_by_index[sg_idx] = {
                                "status": "error",
                                "message": str(exc),
                                "data": {"tasks": []},
                            }

                for sg_idx, subgoal_dict in enumerate(subgoals_list, 1):
                    logger.info(
                        "  Subgoal %d/%d: %s",
                        sg_idx, len(subgoals_list), subgoal_dict.get("title", "?"),
                    )
                    tasks_result = task_results_by_index.get(
                        sg_idx,
                        {"status": "error", "message": "No task result", "data": {"tasks": []}},
                    )
                    tasks_list = []

                    if tasks_result.get("status") == "success":
                        tasks_list = tasks_result["data"]["tasks"][:MAX_TASKS_PER_SUBGOAL]
                    else:
                        generation_error = {
                            "stage": "task_generation",
                            "message": tasks_result.get("message", "Task generation failed."),
                            "milestone_title": milestone_dict.get("title", ""),
                            "milestone_index": m_idx,
                            "subgoal_title": subgoal_dict.get("title", ""),
                            "subgoal_index": sg_idx,
                        }
                        logger.warning(
                            "  Subgoal %d — task generation failed, keeping subgoal with no tasks",
                            sg_idx,
                        )
                        partial_failures.append(generation_error)

                    subgoal_entry = {
                        "subgoal_data": subgoal_dict,
                        "tasks": tasks_list,
                    }
                    if tasks_result.get("status") != "success":
                        subgoal_entry["generation_error"] = generation_error
                    milestone_entry["subgoals"].append(subgoal_entry)
                    total_subgoals += 1
                    total_tasks += len(tasks_list)

                all_milestones_data.append(milestone_entry)

                # Update progress proportionally as milestones complete
                progress = 10 + int((m_idx / len(milestones_list)) * 85)
                job.update_progress(
                    progress,
                    f"Milestone {m_idx}/{len(milestones_list)} complete",
                )

            stats = {
                "milestones_total": len(all_milestones_data),
                "subgoals_total":   total_subgoals,
                "tasks_total":      total_tasks,
            }
            timeline_days = None
            try:
                start = goal_data.get("start_date")
                target = goal_data.get("target_date")
                if isinstance(start, str):
                    start = datetime.strptime(start, "%Y-%m-%d").date()
                if isinstance(target, str):
                    target = datetime.strptime(target, "%Y-%m-%d").date()
                if start and target:
                    timeline_days = max(1, (target - start).days + 1)
            except Exception:
                timeline_days = None

            quality_assessment = OutputValidator.assess_hierarchy_quality(
                hierarchy={"milestones": all_milestones_data},
                timeline_days=timeline_days,
                experience_level=(user_context or {}).get("experience_level", "beginner"),
                constraints=(user_context or {}).get("constraints", []),
            )

            output_data = {
                "milestones": all_milestones_data,
                "stats": stats,
                "quality_assessment": quality_assessment,
                "partial_failure_count": len(partial_failures),
                "partial_failures": partial_failures,
            }

            if mark_job_completed:
                # Synchronous callers can mark completion here because they persist immediately after return.
                job.mark_completed(
                    output_data=output_data,
                    model_used=self.provider.model,
                )
            else:
                # Async callers still need to persist the hierarchy into goal tables first.
                job.update_progress(95, "Hierarchy generated. Saving your plan...")

            logger.info(
                "Hierarchy complete — milestones: %d, subgoals: %d, tasks: %d",
                stats["milestones_total"], stats["subgoals_total"], stats["tasks_total"],
            )

            return {
                "status": "success",
                "data": output_data,
                "job_id": str(job.id),
                "message": (
                    f"Generated {stats['milestones_total']} milestones, "
                    f"{stats['subgoals_total']} subgoals, "
                    f"{stats['tasks_total']} tasks. "
                    f"Quality score: {quality_assessment.get('overall_score', 0)}."
                    + (
                        f" Partial failures: {len(partial_failures)}."
                        if partial_failures
                        else ""
                    )
                ),
            }

        except Exception as exc:
            logger.exception(
                "Hierarchy generation failed for goal '%s': %s",
                goal_data.get("title"), exc,
            )
            # FIX: mark_failed() handles status + retry_count atomically
            job.mark_failed(error_message=str(exc))
            return {
                "status": "error",
                "message": str(exc),
                "job_id": str(job.id),
            }

    # -------------------------------------------------------------------------
    # Private generation methods
    # -------------------------------------------------------------------------

    def _generate_milestones(
        self, goal_data: dict, user_context: dict | None
    ) -> dict:
        """Generate monthly milestones from a goal_data dict."""
        months = self._calculate_months(goal_data)
        try:
            logger.info("Generating milestones for %d months", months)

            response = self.provider.generate_response(
                prompt=self.prompts.get_milestone_generating_prompt(goal_data, months),
                system_prompt=(
                    "You are an expert life coach and planning specialist. "
                    "Break down the goal into clear monthly milestones. "
                    "Each milestone must be achievable in ~30 days, build on the previous, "
                    "and have specific, measurable success criteria. "
                    "Respond with valid JSON only — no prose, no markdown fences."
                ),
            )

            parsed = self.milestone_parser.parse_milestones(response.content)
            milestones = (
                parsed.get("milestones", [parsed]) if isinstance(parsed, dict)
                else parsed if isinstance(parsed, list)
                else []
            )

            logger.info("Parsed %d milestones", len(milestones))
            return self.formatter.format_success(
                data={"milestones": milestones},
                message=f"Generated {len(milestones)} milestones",
            )

        except Exception as exc:
            fallback_milestones = self._build_fallback_milestones(
                goal_data=goal_data,
                user_context=user_context,
                months=months,
            )
            if fallback_milestones:
                logger.warning(
                    "Milestone generation failed; using deterministic fallback milestones for goal '%s': %s",
                    goal_data.get("title", ""),
                    exc,
                )
                return self.formatter.format_success(
                    data={"milestones": fallback_milestones},
                    message="Generated fallback milestones after LLM routing failure",
                )

            logger.exception("Milestone generation failed: %s", exc)
            return self.formatter.format_error(
                error_message=str(exc),
                error_code="MILESTONE_GENERATION_FAILED",
            )

    def _generate_subgoals(self, milestone_data: dict, goal_data: dict) -> dict:
        """
        Generate weekly subgoals for one milestone.
        goal_data is passed so the AI has the full goal context, not just
        the milestone title.
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_subgoal_generating_prompt(milestone_data, goal_data),
                system_prompt=(
                    "You are a weekly planning expert. "
                    "Break this monthly milestone into exactly 4 focused weekly subgoals. "
                    "Each subgoal must be specific, actionable, and completable in 7 days. "
                    "Respond with valid JSON containing a 'subgoals' array. No prose."
                ),
            )

            parsed = self.parser.parse_json(response.content)
            subgoals = (
                parsed["subgoals"] if isinstance(parsed, dict) and "subgoals" in parsed
                else parsed if isinstance(parsed, list)
                else []
            )

            logger.info("Parsed %d subgoals", len(subgoals))
            return self.formatter.format_success(
                data={"subgoals": subgoals},
                message=f"Generated {len(subgoals)} subgoals",
            )

        except Exception as exc:
            fallback_subgoals = self._build_fallback_subgoals(
                milestone_data=milestone_data,
                goal_data=goal_data,
            )
            if fallback_subgoals:
                logger.warning(
                    "Subgoal generation failed; using deterministic fallback subgoals for milestone '%s': %s",
                    milestone_data.get("title", ""),
                    exc,
                )
                return self.formatter.format_success(
                    data={"subgoals": fallback_subgoals},
                    message="Generated fallback subgoals after LLM routing failure",
                )

            logger.exception("Subgoal generation failed: %s", exc)
            return self.formatter.format_error(
                error_message=str(exc),
                error_code="SUBGOAL_GENERATION_FAILED",
            )

    def _generate_tasks(self, subgoal_data: dict, milestone_data: dict, goal_data: dict) -> dict:
        """
        Generate daily tasks for one subgoal.
        milestone_data is passed so the AI knows the broader monthly theme.
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_task_generating_prompt(subgoal_data, milestone_data, goal_data),
                system_prompt=(
                    "You are a daily task planner. "
                    "Create specific, actionable tasks that follow the provided category instructions. "
                    "Each task must include title, description, item_type, duration_minutes, "
                    "frequency, difficulty_level, sequence_position, rationale, why_this, "
                    "how_it_helps_you, how_to_do_it, and your_log_placeholder. "
                    "Use a mix of science-backed credibility and grounded motivation. "
                    "Never sound generic or preachy. "
                    "Respond with valid JSON containing a 'tasks' array. No prose."
                ),
            )

            parsed = self.parser.parse_json(response.content)
            tasks = (
                parsed["tasks"] if isinstance(parsed, dict) and "tasks" in parsed
                else parsed if isinstance(parsed, list)
                else []
            )

            logger.info("Parsed %d tasks", len(tasks))
            return self.formatter.format_success(
                data={"tasks": tasks},
                message=f"Generated {len(tasks)} tasks",
            )

        except Exception as exc:
            fallback_tasks = self._build_fallback_tasks(
                subgoal_data=subgoal_data,
                milestone_data=milestone_data,
                goal_data=goal_data,
            )
            if fallback_tasks:
                logger.warning(
                    "Task generation failed; using deterministic fallback tasks for subgoal '%s': %s",
                    subgoal_data.get("title", ""),
                    exc,
                )
                return self.formatter.format_success(
                    data={"tasks": fallback_tasks},
                    message="Generated fallback tasks after LLM routing failure",
                )

            logger.exception("Task generation failed: %s", exc)
            return self.formatter.format_error(
                error_message=str(exc),
                error_code="TASK_GENERATION_FAILED",
            )

    def _build_fallback_tasks(
        self,
        *,
        subgoal_data: dict,
        milestone_data: dict,
        goal_data: dict,
    ) -> list[dict[str, Any]]:
        subgoal_title = (subgoal_data.get("title") or "this subgoal").strip()
        milestone_title = (milestone_data.get("title") or "this milestone").strip()
        goal_title = (goal_data.get("title") or "this goal").strip()
        category = (
            goal_data.get("resolved_category")
            or goal_data.get("primary_category")
            or "productivity"
        )
        item_type = FALLBACK_TASK_ITEM_TYPE_BY_CATEGORY.get(category, "task")
        week_number = self._resolve_week_number(subgoal_data)
        templates = self._build_category_fallback_task_templates(
            category=category,
            item_type=item_type,
            week_number=week_number,
            subgoal_title=subgoal_title,
            milestone_title=milestone_title,
            goal_title=goal_title,
        )

        return [
            {
                **self._enrich_task_copy_fields(
                    task_data=template,
                    goal_title=goal_title,
                    milestone_title=milestone_title,
                    subgoal_title=subgoal_title,
                ),
                "item_type": template.get("item_type") or item_type,
                "sequence_position": index,
            }
            for index, template in enumerate(templates, 1)
        ]

    @staticmethod
    def _enrich_task_copy_fields(
        *,
        task_data: dict[str, Any],
        goal_title: str,
        milestone_title: str,
        subgoal_title: str,
    ) -> dict[str, Any]:
        enriched = dict(task_data)
        title = str(task_data.get("title") or "this task").strip()
        description = str(task_data.get("description") or "").strip()
        rationale = str(task_data.get("rationale") or "").strip()

        how_to_do_it = task_data.get("how_to_do_it")
        if not isinstance(how_to_do_it, list) or not how_to_do_it:
            steps = []
            if description:
                for segment in re.split(r"(?:\n+|\s+\d+\.\s+)", description):
                    cleaned = str(segment).strip(" -\n\r\t.")
                    if cleaned:
                        steps.append(cleaned)
            if not steps:
                steps = [
                    f"Open a focused work block for {title.lower()}.",
                    f"Complete the main action linked to {subgoal_title.lower()}.",
                    "Capture one note so the next session starts faster.",
                ]
            enriched["how_to_do_it"] = steps[:5]

        if not enriched.get("why_this"):
            enriched["why_this"] = (
                rationale
                or f"Doing this today turns {subgoal_title} into visible progress instead of intention. "
                f"It keeps momentum moving inside {milestone_title} while the work is still fresh."
            )

        if not enriched.get("how_it_helps_you"):
            enriched["how_it_helps_you"] = (
                f"This builds practical traction for {goal_title} by strengthening follow-through and reducing restart friction. "
                "A small completed rep today makes the next rep easier to begin."
            )

        if not enriched.get("your_log_placeholder"):
            enriched["your_log_placeholder"] = (
                "When you complete this, note what became clearer, easier, or more repeatable for your larger goal."
            )

        if not enriched.get("description"):
            enriched["description"] = (
                enriched["how_to_do_it"][0]
                if isinstance(enriched["how_to_do_it"], list) and enriched["how_to_do_it"]
                else rationale
            )

        return enriched

    @staticmethod
    def _resolve_week_number(subgoal_data: dict) -> int:
        explicit = subgoal_data.get("week_number")
        if isinstance(explicit, int) and explicit > 0:
            return explicit

        display_order = subgoal_data.get("display_order")
        if isinstance(display_order, int) and display_order >= 0:
            return display_order + 1

        title = str(subgoal_data.get("title") or "")
        match = re.search(r"week\s+(\d+)", title, flags=re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
        return 1

    def _build_category_fallback_task_templates(
        self,
        *,
        category: str,
        item_type: str,
        week_number: int,
        subgoal_title: str,
        milestone_title: str,
        goal_title: str,
    ) -> list[dict[str, Any]]:
        normalized_category = str(category or "").strip().lower()
        if normalized_category in {"fitness", "health", "wellness", "nutrition"}:
            return self._build_health_fallback_tasks(
                category=normalized_category,
                item_type=item_type,
                week_number=week_number,
                subgoal_title=subgoal_title,
                milestone_title=milestone_title,
                goal_title=goal_title,
            )
        return self._build_general_fallback_tasks(
            item_type=item_type,
            week_number=week_number,
            subgoal_title=subgoal_title,
            milestone_title=milestone_title,
            goal_title=goal_title,
        )

    @staticmethod
    def _build_health_fallback_tasks(
        *,
        category: str,
        item_type: str,
        week_number: int,
        subgoal_title: str,
        milestone_title: str,
        goal_title: str,
    ) -> list[dict[str, Any]]:
        if category in {"fitness", "health"}:
            focus_by_week = {
                1: {
                    "title": f"Complete one baseline training session for {subgoal_title}",
                    "description": (
                        f"Do one easy 20-30 minute session tied to {subgoal_title}. "
                        f"Record pace, breathing, and energy so Month work for {milestone_title} starts from a real baseline."
                    ),
                    "duration_minutes": 30,
                    "difficulty_level": 2,
                    "rationale": f"A baseline session makes progress on {goal_title} measurable instead of guesswork.",
                },
                2: {
                    "title": f"Run one technique-focused session for {subgoal_title}",
                    "description": (
                        f"Complete one controlled session that improves form or pacing for {subgoal_title}. "
                        "Keep the effort sustainable and note one technique cue to repeat next time."
                    ),
                    "duration_minutes": 35,
                    "difficulty_level": 3,
                    "rationale": f"Week 2 should turn the initial baseline from {goal_title} into repeatable execution.",
                },
                3: {
                    "title": f"Complete one progression workout for {subgoal_title}",
                    "description": (
                        f"Repeat a core workout from {subgoal_title} and improve one metric such as distance, pace, or consistency. "
                        "Stop while form still feels controlled."
                    ),
                    "duration_minutes": 40,
                    "difficulty_level": 3,
                    "rationale": f"Progressive overload keeps {goal_title} moving without spiking injury risk.",
                },
            }
            primary = focus_by_week.get(week_number, {
                "title": f"Complete one benchmark session for {subgoal_title}",
                "description": (
                    f"Run one benchmark session linked to {subgoal_title} and compare the result against earlier weeks in {milestone_title}. "
                    "Write down what improved and what still feels hard."
                ),
                "duration_minutes": 35,
                "difficulty_level": 3,
                "rationale": f"A benchmark session closes the loop on {goal_title} and sets up the next block.",
            })

            return [
                {
                    **primary,
                    "item_type": item_type,
                    "frequency": "once",
                    "is_prerequisite": True,
                    "trigger_after_days": 0,
                },
                {
                    "title": f"Schedule the next 2 training blocks for {subgoal_title}",
                    "description": (
                        f"Pick two exact time slots for the next sessions in {subgoal_title}. "
                        f"Put them on your calendar and make sure they fit the broader target for {milestone_title}."
                    ),
                    "item_type": "task",
                    "duration_minutes": 15,
                    "frequency": "once",
                    "difficulty_level": 1,
                    "is_prerequisite": False,
                    "trigger_after_days": 0,
                    "rationale": f"Scheduling the next two blocks protects momentum on {goal_title} when the week gets busy.",
                },
                {
                    "title": f"Log recovery notes after the main session for {subgoal_title}",
                    "description": (
                        "Write down how the session felt, what body signals showed up, and the next small adjustment to make. "
                        "Keep the note short enough to reuse before the next workout."
                    ),
                    "item_type": "habit" if item_type == "physical" else item_type,
                    "duration_minutes": 10,
                    "frequency": "once",
                    "difficulty_level": 1,
                    "is_prerequisite": False,
                    "trigger_after_days": 0,
                    "rationale": "A quick review makes the next session easier to start and safer to progress.",
                },
            ]

        wellness_focus_by_week = {
            1: "Build a realistic baseline routine",
            2: "Repeat one calming practice consistently",
            3: "Strengthen one recovery habit under stress",
        }
        wellness_focus = wellness_focus_by_week.get(week_number, "Review what actually reduced stress")
        return [
            {
                "title": f"Practice one 10-minute reset for {subgoal_title}",
                "description": (
                    f"Choose one short reset practice that supports {wellness_focus.lower()} for {subgoal_title}. "
                    "Do it once today and note the best time of day to repeat it."
                ),
                "item_type": item_type,
                "duration_minutes": 10,
                "frequency": "once",
                "difficulty_level": 1,
                "is_prerequisite": True,
                "trigger_after_days": 0,
                "rationale": f"A short repeatable reset is more likely to stick while building {goal_title}.",
            },
            {
                "title": f"Prepare one environment cue for {subgoal_title}",
                "description": (
                    f"Set up one visible cue that makes {subgoal_title} easier to start, such as a reminder, journal, water bottle, or wind-down trigger. "
                    f"Place it where you will see it during {milestone_title}."
                ),
                "item_type": "ritual" if category == "wellness" else item_type,
                "duration_minutes": 5,
                "frequency": "once",
                "difficulty_level": 1,
                "is_prerequisite": False,
                "trigger_after_days": 0,
                "rationale": "Environment cues reduce startup friction when energy is low.",
            },
            {
                "title": f"Write one short reflection for {subgoal_title}",
                "description": (
                    "Note what improved your energy or calm today, what triggered stress, and the one small change to repeat tomorrow. "
                    "Use 3-5 sentences only."
                ),
                "item_type": "cognitive",
                "duration_minutes": 10,
                "frequency": "once",
                "difficulty_level": 1,
                "is_prerequisite": False,
                "trigger_after_days": 0,
                "rationale": f"A short reflection turns {goal_title} into a learnable routine instead of a vague intention.",
            },
        ]

    @staticmethod
    def _build_general_fallback_tasks(
        *,
        item_type: str,
        week_number: int,
        subgoal_title: str,
        milestone_title: str,
        goal_title: str,
    ) -> list[dict[str, Any]]:
        primary_by_week = {
            1: {
                "title": f"Define the first concrete deliverable for {subgoal_title}",
                "description": (
                    f"Write down the exact output that proves {subgoal_title} has started. "
                    f"Keep the deliverable small enough to finish inside {milestone_title}."
                ),
                "duration_minutes": 20,
                "difficulty_level": 1,
                "rationale": f"Week 1 needs a visible starting point so {goal_title} does not stay abstract.",
            },
            2: {
                "title": f"Produce one focused work output for {subgoal_title}",
                "description": (
                    f"Spend one uninterrupted block creating a real output for {subgoal_title}. "
                    "Finish one meaningful unit before switching context."
                ),
                "duration_minutes": 35,
                "difficulty_level": 2,
                "rationale": f"Week 2 should convert planning for {goal_title} into visible work.",
            },
            3: {
                "title": f"Ship one progress checkpoint for {subgoal_title}",
                "description": (
                    f"Complete one concrete checkpoint for {subgoal_title} and save it in a form you can review later. "
                    "Do not expand scope mid-session."
                ),
                "duration_minutes": 40,
                "difficulty_level": 3,
                "rationale": f"A checkpoint makes momentum on {goal_title} reviewable and easier to continue.",
            },
        }
        primary = primary_by_week.get(week_number, {
            "title": f"Review and tighten the next step for {subgoal_title}",
            "description": (
                f"Check what is complete in {subgoal_title}, remove one low-value action, and define the highest-value next step for the next block in {milestone_title}."
            ),
            "duration_minutes": 20,
            "difficulty_level": 1,
            "rationale": f"A review week keeps {goal_title} from drifting into busywork.",
        })

        return [
            {
                **primary,
                "item_type": item_type,
                "frequency": "once",
                "is_prerequisite": True,
                "trigger_after_days": 0,
            },
            {
                "title": f"Complete one 30-minute deep-work block for {subgoal_title}",
                "description": (
                    f"Set a 30-minute timer and work only on the highest-value action for {subgoal_title}. "
                    "Stop when the timer ends and capture what remains."
                ),
                "item_type": "cognitive" if item_type == "task" else item_type,
                "duration_minutes": 30,
                "frequency": "once",
                "difficulty_level": 2,
                "is_prerequisite": False,
                "trigger_after_days": 0,
                "rationale": "A short deep-work block creates forward motion even when generation is degraded.",
            },
            {
                "title": f"Capture blockers and the next move for {subgoal_title}",
                "description": (
                    "Write down what moved forward, what blocked you, and the next action to continue. "
                    "Keep the note brief enough to review before your next session."
                ),
                "item_type": "cognitive",
                "duration_minutes": 10,
                "frequency": "once",
                "difficulty_level": 1,
                "is_prerequisite": False,
                "trigger_after_days": 0,
                "rationale": f"A short review loop helps {goal_title} survive interruptions without losing clarity.",
            },
        ]

    def _build_fallback_milestones(
        self,
        *,
        goal_data: dict,
        user_context: dict | None,
        months: int,
    ) -> list[dict[str, Any]]:
        goal_title = (goal_data.get("title") or "this goal").strip()
        start_date, target_date = self._resolve_goal_dates(goal_data)
        month_count = max(1, min(MAX_MILESTONES, months))
        if not start_date:
            start_date = datetime.utcnow().date()
        total_days = ((target_date - start_date).days + 1) if target_date else month_count * 30
        days_per_month = max(1, math.ceil(total_days / month_count))
        constraints = (user_context or {}).get("constraints") or []
        constraint_note = f" while working around {constraints[0]}" if constraints else ""

        milestones: list[dict[str, Any]] = []
        for index in range(month_count):
            month_start = start_date + timedelta(days=index * days_per_month)
            month_end = month_start + timedelta(days=days_per_month - 1)
            if target_date:
                month_end = min(month_end, target_date)
            milestones.append(
                {
                    "title": f"Month {index + 1}: Build momentum for {goal_title}",
                    "description": (
                        f"Focus this month on creating steady progress toward {goal_title}{constraint_note}."
                    ),
                    "success_criteria": [
                        f"Complete at least 3 focused work sessions for {goal_title}",
                        "Document weekly progress and blockers",
                        "Finish the month's highest-priority action before moving on",
                    ],
                    "priority": "high" if index == 0 else "medium",
                    "start_date": month_start.isoformat(),
                    "target_date": month_end.isoformat(),
                    "ai_reasoning": "Fallback milestone generated because AI routing was unavailable.",
                }
            )
        return milestones

    def _build_fallback_subgoals(
        self,
        *,
        milestone_data: dict,
        goal_data: dict,
    ) -> list[dict[str, Any]]:
        milestone_title = (milestone_data.get("title") or "this milestone").strip()
        goal_title = (goal_data.get("title") or "this goal").strip()
        milestone_start, milestone_target = self._resolve_range_dates(
            milestone_data.get("start_date"),
            milestone_data.get("target_date"),
        )
        subgoal_count = max(1, MAX_SUBGOALS_PER_MILESTONE)
        total_days = ((milestone_target - milestone_start).days + 1) if (milestone_start and milestone_target) else subgoal_count * 7
        days_per_subgoal = max(1, math.ceil(total_days / subgoal_count))

        subgoals: list[dict[str, Any]] = []
        for index in range(subgoal_count):
            subgoal_start = milestone_start + timedelta(days=index * days_per_subgoal) if milestone_start else None
            subgoal_end = subgoal_start + timedelta(days=days_per_subgoal - 1) if subgoal_start else None
            if subgoal_end and milestone_target:
                subgoal_end = min(subgoal_end, milestone_target)
            subgoals.append(
                {
                    "title": f"Week {index + 1}: Advance {goal_title}",
                    "description": (
                        f"Push one concrete part of {milestone_title} forward and leave a clear next step."
                    ),
                    "priority": "medium",
                    "start_date": subgoal_start.isoformat() if subgoal_start else None,
                    "target_date": subgoal_end.isoformat() if subgoal_end else None,
                    "ai_reasoning": "Fallback subgoal generated because AI routing was unavailable.",
                }
            )
        return subgoals

    @staticmethod
    def _parse_iso_date(value):
        if not value:
            return None
        if hasattr(value, "isoformat") and not isinstance(value, str):
            return value
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except Exception:
            return None

    def _resolve_goal_dates(self, goal_data: dict):
        start_date = self._parse_iso_date(goal_data.get("start_date"))
        target_date = self._parse_iso_date(goal_data.get("target_date"))
        if start_date and target_date and target_date < start_date:
            target_date = start_date
        return start_date, target_date

    def _resolve_range_dates(self, start_value, target_value):
        start_date = self._parse_iso_date(start_value)
        target_date = self._parse_iso_date(target_value)
        if start_date and target_date and target_date < start_date:
            target_date = start_date
        if not start_date and target_date:
            start_date = target_date
        if start_date and not target_date:
            target_date = start_date + timedelta(days=20)
        return start_date, target_date

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    @staticmethod
    def _calculate_months(goal_data: dict) -> int:
        """
        Derive planned months from start_date and target_date.
        Accepts both date objects and ISO strings.
        Falls back to DEFAULT_MONTHS if dates are missing or invalid.
        """
        try:
            start  = goal_data.get("start_date")
            target = goal_data.get("target_date")
            if not start or not target:
                return DEFAULT_MONTHS

            if isinstance(start, str):
                start  = datetime.strptime(start,  "%Y-%m-%d").date()
            if isinstance(target, str):
                target = datetime.strptime(target, "%Y-%m-%d").date()

            days = max(1, (target - start).days + 1)
            months = math.ceil(days / 30)
            return max(MIN_MONTHS, min(MAX_MONTHS, months))

        except Exception as exc:
            logger.warning("Could not calculate months from dates: %s — using default.", exc)
            return DEFAULT_MONTHS
