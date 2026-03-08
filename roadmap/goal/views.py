# ==============================================================================
# roadmap/goal/views.py  — Three views, nothing more
# ==============================================================================
#
# VIEW MAP (matches your UI exactly):
#
#   GoalListAPIView              GET  /api/goals/
#     → Goals page: Life Area cards + goal cards with progress
#     → Supports ?status= ?category= ?priority= filters
#
#   GoalCreateWithHierarchyView  POST /api/goals/
#     → Creates goal + AI hierarchy in one call
#
#   GoalHierarchyAPIView         GET  /api/goals/<goal_id>/hierarchy/
#     → Goals page expanded view: milestones + subgoals (NO tasks here)
#     → Tasks live on the Routine page, not here
#
# That's it. No GoalDetailLightweightAPIView, no GoalDetailWithHierarchyAPIView.
# ==============================================================================




from django.shortcuts import render
from django.core.exceptions import ImproperlyConfigured
from .serializers import UserCurrentSituationGoalSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserCurrentSituationGoal, Goal, Milestone, SubGoal, Task, GoalAttributes, CommitmentContract
from .serializers import (
    GoalSerializer,
    GoalListSerializer,
    MilestoneSerializer,
    SubGoalSerializer,
    TaskSerializer,
    CommitmentContractSerializer,
    CommitmentContractSignSerializer,
)
from django.utils import timezone
from ai.models import AIProcessingJob
from ai.config import (
    build_ai_runtime_error_message,
    get_missing_ai_env_vars,
    get_ai_debug_enabled,
)
from ai.services.text_extraction import GoalAttributeExtractor
from ai.services.GoalHierarchyGenerator import GoalHierarchyGenerator
from rest_framework import status
import threading
import json
from authentication.models import UserPersonalDetails
from django.db.models import Prefetch, Count, Avg, Q, Sum
from django.db import close_old_connections
from django.db import transaction
from django.http import Http404
from rest_framework.throttling import UserRateThrottle
import logging

from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework.exceptions import NotFound, ValidationError
from common.ownership import get_owned_object_or_404
from goal.core.response import success_response, error_response, created_response
from goal.services.commitment_contract import (
    build_goal_snapshots,
    generate_contract_pdf_bytes,
    send_contract_email_via_resend,
    build_contract_email_html,
)
from goal.services.goal_domain import (
    build_goal_hierarchy_payload,
    build_goal_seed_data,
    create_goal_for_user,
    get_goal_with_hierarchy_for_user,
    get_user_goals_payload,
)


logger = logging.getLogger(__name__)


# Create your views here.

# Priority sort order used in Python (CharField can't sort high>medium>low in DB)
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}




class GoalProductionApiView(APIView):
    """
    Base API view for production environment with enhanced logging and error handling.
    """

    throttle_classes = [UserRateThrottle]

    def handle_exception(self, exc):
        """
        Global exception handler for consistent error responses and logging in production.
        """

        logger.error(
            f"Exception occurred in {self.__class__.__name__}: {str(exc)}",
            exc_info=True,
        )

        # You can add custom exception handling here
        # For production, avoid exposing internal errors to clients. Instead, return a generic error message.
        if isinstance(exc, (TokenError, InvalidToken)):
            return Response(
                {
                    "error": "Token is invalid or expired",
                    "code": "token_not_valid",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Handle specific exceptions

        if isinstance(exc, NotFound):
            return Response(
                {
                    "error": "Resource not found",
                    "code": "not_found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if isinstance(exc, ValidationError):
            return Response(
                {
                    "error": "Validation error",
                    "details": exc.detail if hasattr(exc, "detail") else str(exc),
                    "code": "validation_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().handle_exception(exc)


class UserCurrentSituationGoalAPIView(GoalProductionApiView):

    permission_classes = [IsAuthenticated]
    SITUATION_JOB_TYPE = "situation_analysis"

    def _get_instance(self, user):
        """
        Fetch UserCurrentSituationGoal that belongs to this user.

        FIX: Filter by user on AIProcessingJob so one user cannot access
             another user's data even if they know the job ID.
        """
        job = (
            AIProcessingJob.objects.filter(
                user=user,
                job_type=self.SITUATION_JOB_TYPE,
                status="completed",  # Only return successfully processed results
            )
            .order_by("-created_at")  # Most recent first if there are multiple
            .first()
        )

        if not job:
            return None

        # get_object_or_404 ensures we never return a situation linked to someone else's job
        return get_object_or_404(UserCurrentSituationGoal, ai_processing_job=job)

    def get(self, request):
        """Retrieve the authenticated user's current situation goal."""
        instance = self._get_instance(request.user)

        if not instance:
            return error_response(
                message="No current situation goal found. Please complete your profile setup first.",
                code="No current situation found",
                errors="No current situation goal found. Please complete your profile setup first.",
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserCurrentSituationGoalSerializer(instance)
        return success_response(
            data=serializer.data,
            message="User current situation goal retrieved successfully.",
            status=status.HTTP_200_OK,
        )
        # return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        """Partially update the authenticated user's current situation goal."""
        instance = self._get_instance(request.user)

        if not instance:
            return error_response(
                message="No current situation goal found to update.",
                code="No current situation goal found",
                errors="No current situation goal found to update.",
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserCurrentSituationGoalSerializer(
            instance, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return success_response(
                data=serializer.data,
                message="User current situation goal updated successfully.",
                status=status.HTTP_200_OK,
            )

        return error_response(
            message="User current situation goal update failed.",
            code="Update failed",
            errors=serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request):
        """Delete the authenticated user's current situation goal."""
        instance = self._get_instance(request.user)

        if not instance:
            return error_response(
                message="No current situation goal found to delete.",
                code="No current",
                errors="No current situation goal found to delete.",
                status=status.HTTP_404_NOT_FOUND,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =======================
# # Create Goal API View Here GET and POST
# =======================





class GoalAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return all goals for the authenticated user."""
        detailed = request.query_params.get("detailed", "false").lower() == "true"
        payload = get_user_goals_payload(user=request.user, detailed=detailed)
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        """
        Create a new goal with optional attribute extraction.
        """
        try:
            goal, errors = create_goal_for_user(
                request_data=request.data,
                user=request.user,
                request=request,
            )
            if errors:
                return Response(
                    {"message": "Validation failed", "errors": errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "message": "Goal created successfully!",
                    "goal": GoalSerializer(goal).data,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CreateGoalWithHierarchyAPIView(GoalProductionApiView):
    """
    Creates a Goal and then uses AI to generate a full hierarchy:
      Goal → Milestones (monthly) → SubGoals (weekly) → Tasks (daily)
    Goal → 2-3 Milestones (months) → 4 Subgoals (weeks) each → 7 Tasks (days) each
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _extract_hierarchy_error(result: dict) -> str:
        return (
            result.get("message")
            or result.get("error")
            or result.get("error_message")
            or "Unknown hierarchy generation error"
        )

    def post(self, request):
        try:
            print(f"\n{'='*80}")
            print(f"CREATE GOAL WITH HIERARCHY API Called")
            print(f"{'='*80}\n")

            # 1. Create Goal
            goal, errors = create_goal_for_user(
                request_data=request.data,
                user=request.user,
                request=request,
            )
            if errors:
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)

            logger.info(f"Goal created: {goal.id} - {goal.title}")
            print(f"Goal created: {goal.id} - {goal.title}")

            sync_mode = str(request.query_params.get("sync", "false")).lower() == "true"
            missing_ai_env_vars = get_missing_ai_env_vars()
            ai_runtime_error_message = build_ai_runtime_error_message()
            if get_ai_debug_enabled():
                logger.info(
                    "[AI_DEBUG] create-with-hierarchy request user_id=%s goal_id=%s sync=%s missing_ai_env=%s",
                    request.user.id,
                    goal.id,
                    sync_mode,
                    ",".join(missing_ai_env_vars) if missing_ai_env_vars else "none",
                )
            if not sync_mode:
                job = AIProcessingJob.objects.create(
                    user=request.user,
                    job_type="milestone_generation",
                    input_data={
                        "goal_id": str(goal.id),
                        "goal_title": goal.title,
                        "target_date": str(goal.target_date or ""),
                    },
                    metadata={
                        "goal_id": str(goal.id),
                        "progress_message": "Queued for hierarchy generation...",
                    },
                    status="pending",
                    progress_percentage=0,
                )

                if missing_ai_env_vars:
                    job.metadata = {
                        **(job.metadata or {}),
                        "progress_message": "Hierarchy generation unavailable: AI runtime is not configured.",
                    }
                    job.save(update_fields=["metadata", "updated_at"])
                    job.mark_failed(ai_runtime_error_message)
                    return Response(
                        {
                            "message": "Goal created, but hierarchy generation is unavailable until AI runtime is configured.",
                            "goal": GoalSerializer(goal).data,
                            "job": {
                                "id": str(job.id),
                                "status": job.status,
                                "progress_percentage": job.progress_percentage,
                                "progress_message": (job.metadata or {}).get("progress_message", ""),
                                "poll_url": f"/ai/jobs/{job.id}/",
                                "estimated_seconds": 0,
                                "error_message": job.error_message,
                            },
                        },
                        status=status.HTTP_202_ACCEPTED,
                    )

                estimated_seconds = self._estimate_generation_seconds(goal)
                worker = threading.Thread(
                    target=self._run_hierarchy_generation_async,
                    kwargs={
                        "goal_id": str(goal.id),
                        "user_id": request.user.id,
                        "job_id": str(job.id),
                    },
                    daemon=True,
                )
                worker.start()

                return Response(
                    {
                        "message": "Goal created. Hierarchy generation started.",
                        "goal": GoalSerializer(goal).data,
                        "job": {
                            "id": str(job.id),
                            "status": job.status,
                            "progress_percentage": job.progress_percentage,
                            "progress_message": "Queued for hierarchy generation...",
                            "poll_url": f"/ai/jobs/{job.id}/",
                            "estimated_seconds": estimated_seconds,
                        },
                    },
                    status=status.HTTP_202_ACCEPTED,
                )

            goal_data = build_goal_seed_data(goal)
            # Get user context
            user_context = self._get_user_context(request.user)
            if missing_ai_env_vars:
                return Response(
                    {
                        "message": "Goal created, but hierarchy generation is unavailable until AI runtime is configured.",
                        "goal": GoalSerializer(goal).data,
                        "error": ai_runtime_error_message,
                    },
                    status=status.HTTP_201_CREATED,
                )
            # 2. Generate Complete Hierarchy
            generator = GoalHierarchyGenerator()

            hierarchy_result = generator.generate_complete_hierarchy(
                goal_data=goal_data,
                user=request.user,
                user_context=user_context,
            )


            if hierarchy_result.get("status") != "success":
                hierarchy_error = self._extract_hierarchy_error(hierarchy_result)
                logger.warning(
                    "Hierarchy generation failed for goal %s: %s",
                    goal.id,
                    hierarchy_error,
                )
                return Response(
                    {
                        "message": "Goal created, but hierarchy generation failed.",
                        "goal": GoalSerializer(goal).data,
                        "error": hierarchy_error,
                    },
                    status=status.HTTP_201_CREATED,
                )

            # 3. Save Complete Hierarchy to Database
            saved_counts = self._save_complete_hierarchy_to_db(
                goal, hierarchy_result.get("data", {})
            )

            logger.info(
                "Hierarchy saved for goal %s — milestones: %d, subgoals: %d, tasks: %d",
                goal.id,
                saved_counts["milestones"],
                saved_counts["subgoals"],
                saved_counts["tasks"],
            )
            print(f"\n{'='*80}")
            print(f"HIERARCHY GENERATION COMPLETE")
            print(f"{'='*80}")
            print(f"Milestones saved: {saved_counts['milestones']}")
            print(f"Subgoals saved: {saved_counts['subgoals']}")
            print(f"Tasks saved: {saved_counts['tasks']}")
            print(f"Total items: {sum(saved_counts.values())}")
            print(f"{'='*80}\n")

            return Response(
                {
                    "message": "Goal created with complete hierarchy!",
                "goal": GoalSerializer(goal).data,
                "hierarchy": {
                    "milestones_saved": saved_counts["milestones"],
                    "subgoals_saved": saved_counts["subgoals"],
                    "tasks_saved": saved_counts["tasks"],
                        "total_items": sum(saved_counts.values()),
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            print(f"Error: {str(e)}")
            import traceback

            traceback.print_exc()
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _run_hierarchy_generation_async(self, goal_id: str, user_id: int, job_id: str):
        try:
            user = None
            from authentication.models import CustomUser
            user = CustomUser.objects.get(id=user_id)
            goal = Goal.objects.get(id=goal_id, user=user)

            goal_data = build_goal_seed_data(goal)
            user_context = self._get_user_context(user)
            generator = GoalHierarchyGenerator()

            hierarchy_result = generator.generate_complete_hierarchy(
                goal_data=goal_data,
                user=user,
                user_context=user_context,
                existing_job_id=job_id,
            )

            if hierarchy_result.get("status") != "success":
                hierarchy_error = self._extract_hierarchy_error(hierarchy_result)
                logger.warning(
                    "Async hierarchy generation failed for goal %s: %s",
                    goal.id,
                    hierarchy_error,
                )
                return

            saved_counts = self._save_complete_hierarchy_to_db(
                goal, hierarchy_result.get("data", {})
            )
            logger.info(
                "Async hierarchy saved for goal %s — milestones: %d, subgoals: %d, tasks: %d",
                goal.id,
                saved_counts["milestones"],
                saved_counts["subgoals"],
                saved_counts["tasks"],
            )
        except ImproperlyConfigured:
            logger.warning(
                "Async hierarchy generation skipped for goal %s: %s",
                goal_id,
                build_ai_runtime_error_message(),
            )
            try:
                failed_job = AIProcessingJob.objects.get(id=job_id, user_id=user_id)
                failed_job.mark_failed(build_ai_runtime_error_message())
            except Exception:
                logger.exception(
                    "Could not mark async job as failed for missing AI runtime config: %s",
                    job_id,
                )
        except Exception:
            logger.exception("Async hierarchy worker failed for goal %s", goal_id)
            try:
                failed_job = AIProcessingJob.objects.get(id=job_id, user_id=user_id)
                failed_job.mark_failed("Unexpected error in async hierarchy worker.")
            except Exception:
                logger.exception("Could not mark async job as failed: %s", job_id)
        finally:
            close_old_connections()

    @staticmethod
    def _estimate_generation_seconds(goal: Goal) -> int:
        # Heuristic for UI ETA; real ETA is served by /ai/jobs/<id>/ polling.
        if goal.start_date and goal.target_date:
            days = max(1, (goal.target_date - goal.start_date).days + 1)
        else:
            days = 60
        months = max(1, min(12, (days + 29) // 30))
        milestones = min(months, 6)
        calls_estimate = 1 + milestones + (milestones * 3)
        return max(60, calls_estimate * 20)

    def _get_user_context(self, user):
        """Get user context for better AI generation"""
        try:
            personal = UserPersonalDetails.objects.get(user=user)
            situation = UserCurrentSituationGoal.objects.get(
                user_personal_details=personal
            )
            return {
                "current_role":      situation.current_role,
                "key_skills":        situation.key_skills,
                "constraints":       situation.constraints,
                "priority_areas":    situation.priority_areas,
                "main_goals":        situation.main_goals,
            }
        except UserPersonalDetails.DoesNotExist:
            logger.warning("UserPersonalDetails not found for user %s", user.id)
            return {}
        except UserCurrentSituationGoal.DoesNotExist:
            logger.warning("UserCurrentSituationGoal not found for user %s", user.id)   
            return {}

        except Exception as e:
            print(f"Could not get user context: {e}")
            return {}

    def _save_complete_hierarchy_to_db(self, goal, hierarchy_data):
        """
        FIXED: Save complete hierarchy (milestones + subgoals + tasks) to database

        Expected hierarchy_data structure:
        {
            'milestones': [
                {
                    'milestone_data': {...},
                    'subgoals': [
                        {
                            'subgoal_data': {...},
                            'tasks': [...]
                        }
                    ]
                }
            ]
        }
        """
        saved = {"milestones": 0, "subgoals": 0, "tasks": 0}

        milestones_data = hierarchy_data.get("milestones", [])
        print("\nSAVING HIERARCHY TO DATABASE")
        print(f"Total milestones to process: {len(milestones_data)}")

        for m_idx, milestone_entry in enumerate(hierarchy_data.get("milestones", []), 1):
            milestone_data = milestone_entry.get("milestone_data", {})
            try:
                milestone = self._save_milestone(goal, milestone_data, m_idx)
                saved["milestones"] += 1
            except Exception:
                logger.exception(
                    "Failed to save milestone %d for goal %s", m_idx, goal.id
                )
                continue

            for sg_idx, subgoal_entry in enumerate(milestone_entry.get("subgoals", []), 1):
                subgoal_data = subgoal_entry.get("subgoal_data", {})
                tasks_data   = subgoal_entry.get("tasks", [])
                try:
                    subgoal = self._save_subgoal(milestone, subgoal_data, sg_idx)
                    saved["subgoals"] += 1
                except Exception:
                    logger.exception(
                        "Failed to save subgoal %d for milestone %s", sg_idx, milestone.id
                    )
                    continue

                for t_idx, task_data in enumerate(tasks_data, 1):
                    try:
                        self._save_task(subgoal, task_data, t_idx)
                        saved["tasks"] += 1
                    except Exception:
                        logger.exception(
                            "Failed to save task %d for subgoal %s", t_idx, subgoal.id
                        )

        return saved


    def _save_milestone(self, goal: Goal, data: dict, index: int) -> Milestone:
        """
        FIX: Removed month_year and estimated_duration_days — both were deleted
             from the updated Milestone model. Uses start_date/target_date instead.
        """
        return Milestone.objects.create(
            goal=goal,
            title=data.get("title", f"Month {index}"),
            description=data.get("description", ""),
            # success_criteria is TextField — store as plain text
            success_criteria=self._to_text(data.get("success_criteria", "")),
            priority=data.get("priority", "medium"),
            display_order=index,
            # Dates — use whatever the AI provides; fall back to None (nullable)
            start_date=data.get("start_date") or None,
            target_date=data.get("target_date") or None,
            is_ai_generated=True,
            ai_reasoning=data.get("reasoning", data.get("ai_reasoning", "")),
        )

    def _save_subgoal(self, milestone: Milestone, data: dict, index: int) -> SubGoal:
        """
        FIX: Removed learning_objectives, week_number, estimated_duration_days
             — all deleted from the updated SubGoal model.
             week_number is now a @property derived from display_order.
             description covers what learning_objectives used to store.
        """
        return SubGoal.objects.create(
            milestone=milestone,
            title=data.get("title", f"Week {index}"),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            display_order=index - 1,   # display_order is 0-based; week_number = display_order + 1
            start_date=data.get("start_date") or None,
            target_date=data.get("target_date") or None,
            is_ai_generated=True,
            ai_reasoning=data.get("reasoning", data.get("ai_reasoning", "")),
        )

    def _save_task(self, subgoal: SubGoal, data: dict, index: int) -> Task:
        """
        FIX: Removed instructions and resources — both deleted from the updated
             Task model. Their content should be included in description instead.
             The AI prompt should be updated to put step-by-step detail into
             description rather than a separate instructions field.
        """
        # Merge instructions into description if the AI still sends both.
        # AI payloads can return either field as list/text; normalize to string first.
        description = self._to_text(data.get("description", ""))
        instructions = self._to_text(data.get("instructions", ""))
        if instructions and instructions not in description:
            description = f"{description}\n\n{instructions}".strip()

        return Task.objects.create(
            subgoal=subgoal,
            title=data.get("title", f"Task {index}"),
            description=description,
            task_type=data.get("task_type", "learning"),
            priority=data.get("priority", "medium"),
            display_order=index - 1,
            estimated_duration_minutes=data.get("estimated_duration_minutes", 60),
            scheduled_date=data.get("scheduled_date") or None,
            preferred_time_slot=self._normalize_time_slot(data, index),
            is_ai_generated=True,
            ai_reasoning=data.get("reasoning", data.get("ai_reasoning", "")),
        )

    @staticmethod
    def _normalize_time_slot(task_data: dict, index: int) -> str:
        """
        Resolve AI-provided time slot into one of:
        morning | afternoon | evening.
        """
        allowed = {"morning", "afternoon", "evening"}
        for key in ("preferred_time_slot", "time_slot", "suggested_time_slot", "time_of_day"):
            value = task_data.get(key)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in allowed:
                    return normalized

        day_order = task_data.get("day_order")
        if isinstance(day_order, int):
            if day_order <= 2:
                return "morning"
            if day_order <= 4:
                return "afternoon"
            return "evening"

        text = f"{task_data.get('title', '')} {task_data.get('description', '')}".lower()
        if any(word in text for word in ("morning", "am", "breakfast", "wake", "early")):
            return "morning"
        if any(word in text for word in ("evening", "night", "pm", "journal", "reflect")):
            return "evening"

        # Index fallback for stable distribution if AI omits the field.
        if index <= 2:
            return "morning"
        if index <= 4:
            return "afternoon"
        return "evening"
        
        
    @staticmethod
    def _to_text(value) -> str:
        """Convert a list or any value to a plain string for TextField storage."""
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value)
        return str(value) if value else ""



# ==============================================================================
# VIEW 1 — Goal List + Life Area Summary
# Drives: Life Area cards + goal card list on Goals page
# ==============================================================================

class GoalListAPIView(APIView):
    """
    GET  /api/goals/          → list all goals with life-area summary
    POST /api/goals/          → create goal + AI hierarchy

    Query params for GET:
      ?status=in_progress
      ?category=financial
      ?priority=high
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Base queryset — annotate counts in DB so we don't loop in Python
        goals = (
            Goal.objects.filter(user=request.user)
            .annotate(
                milestone_count=Count("milestones", distinct=True),
                completed_milestones=Count(
                    "milestones",
                    filter=Q(milestones__status="completed"),
                    distinct=True,
                ),
            )
            .select_related("attributes")
            .order_by("target_date")  # DB-safe ordering; priority sort done below
        )

        # Optional filters
        if s := request.query_params.get("status"):
            goals = goals.filter(status=s)
        if c := request.query_params.get("category"):
            goals = goals.filter(primary_category=c)
        if p := request.query_params.get("priority"):
            goals = goals.filter(priority=p)

        # Sort by priority (high→medium→low) then target_date
        goals = sorted(goals, key=lambda g: (PRIORITY_ORDER.get(g.priority, 9), g.target_date or timezone.localdate()))

        # --- Life Area summary (drives the 4 category cards in your UI) ------
        categories = ["financial", "career", "health", "personal"]
        life_areas = {}
        for cat in categories:
            cat_goals = [g for g in goals if g.primary_category == cat]
            total = len(cat_goals)
            completed = sum(1 for g in cat_goals if g.status == "completed")
            avg_progress = (
                round(sum(g.progress_percentage for g in cat_goals) / total)
                if total else 0
            )
            life_areas[cat] = {
                "goal_count":         total,
                "completed":          completed,
                "avg_progress":       avg_progress,
            }

        # --- Goal cards -------------------------------------------------------
        goals_data = []
        today = timezone.localdate()

        for goal in goals:
            days_left = goal.days_remaining  # @property on model
            is_overdue = goal.is_overdue     # @property on model

            goals_data.append({
                "id":                  str(goal.id),
                "title":               goal.title,
                "description":         goal.description,
                "why_it_matters":      goal.why_it_matters,
                "primary_category":    goal.primary_category,
                "priority":            goal.priority,
                "status":              goal.status,
                "progress_percentage": goal.progress_percentage,
                "start_date":          goal.start_date.isoformat() if goal.start_date else None,
                "target_date":         goal.target_date.isoformat() if goal.target_date else None,
                "days_remaining":      days_left,
                "is_overdue":          is_overdue,
                "is_ai_generated":     goal.is_ai_generated,
                # Counts for the milestone progress indicator on each card
                "milestone_count":     goal.milestone_count,
                "completed_milestones": goal.completed_milestones,
                # Attributes — only the relevant category field, not all four
                "attributes":          self._get_attributes(goal),
            })

        return Response(
            {
                "life_areas": life_areas,
                "count":      len(goals_data),
                "goals":      goals_data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        """Create a goal and immediately generate the AI hierarchy."""
        return CreateGoalWithHierarchyAPIView().post(request)

    @staticmethod
    def _get_attributes(goal) -> dict | None:
        """Return only the relevant category's attribute data, not all four fields."""
        try:
            attr = goal.attributes  # select_related — no extra query
            field_map = {
                "financial": attr.financial_data,
                "career":    attr.career_data,
                "health":    attr.health_data,
                "personal":  attr.personal_data,
            }
            data = field_map.get(goal.primary_category)
            return {goal.primary_category: data} if data else None
        except GoalAttributes.DoesNotExist:
            return None
        
        

# ==============================================================================
# VIEW 2 — Goal Hierarchy (Milestones + SubGoals + Tasks)
# Drives: Expanded goal card on Goals page
# Now includes full task details with all task information
# ==============================================================================

class GoalHierarchyAPIView(APIView):
    """
    GET /api/goals/<goal_id>/hierarchy/

    Returns complete hierarchy: milestones -> subgoals -> tasks.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        goal = get_goal_with_hierarchy_for_user(goal_id=goal_id, user=request.user)
        if not goal:
            return Response(
                {"error": "Goal not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payload = build_goal_hierarchy_payload(goal=goal, today=timezone.localdate())
        return Response(payload, status=status.HTTP_200_OK)


class GoalDetailAPIView(APIView):
    """
    GET    /goal/goals/<goal_id>/  -> retrieve goal details
    PUT    /goal/goals/<goal_id>/  -> full update
    PATCH  /goal/goals/<goal_id>/  -> partial update
    DELETE /goal/goals/<goal_id>/  -> delete goal and all children (CASCADE)
    """

    permission_classes = [IsAuthenticated]

    def _get_goal(self, goal_id, user):
        try:
            return Goal.objects.get(id=goal_id, user=user)
        except Goal.DoesNotExist:
            return None

    def get(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal)
        return Response({"goal": serializer.data}, status=status.HTTP_200_OK)

    def put(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        goal.delete()  # CASCADE deletes Milestones -> SubGoals -> Tasks automatically
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskDetailApiView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]
    def _get_task(self, task_id, user):
        try:
            return get_owned_object_or_404(
                Task,
                user=user,
                owner_filter="subgoal__milestone__goal__user",
                id=task_id,
            )
        except Http404:
            return None

    
    def get(self, request, task_id):
        task = self._get_task(task_id, request.user)
        if not task:
            return Response({"error": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, task_id):
        task = self._get_task(task_id, request.user)
        
        if not task:
            return Response({"error": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = TaskSerializer(task, data=request.data, partial=True)
        try:
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as err:
            return Response({"error": str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    
    def delete(self, request, task_id):
        task = self._get_task(task_id, request.user)
        if not task:
            return Response({"error": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        task.delete()
        return Response({"message": "Task deleted successfully."},status=status.HTTP_204_NO_CONTENT)


class CommitmentContractAPIView(APIView):
    """
    Commitment contract lifecycle:
    - GET: fetch signed contract or unsigned preview
    - PATCH: update draft fields (only before signing)
    - POST: sign permanently + generate PDF + email via Resend
    - DELETE: forbidden after signing
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _default_identity_statement(user) -> str:
        return (
            f"I am committed to becoming the disciplined version of myself, {user.email}, "
            "who consistently honors daily actions and long-term goals."
        )

    def get(self, request):
        contract = CommitmentContract.objects.filter(user=request.user).first()
        goals_snapshot, deadlines_snapshot = build_goal_snapshots(request.user)

        if contract:
            payload = CommitmentContractSerializer(contract).data
            payload["preview_goals"] = goals_snapshot
            payload["preview_deadlines"] = deadlines_snapshot
            return Response(payload, status=status.HTTP_200_OK)

        return Response(
            {
                "id": None,
                "identity_statement": self._default_identity_statement(request.user),
                "signature_name": request.user.email,
                "cc_email": None,
                "goals_snapshot": [],
                "deadlines_snapshot": [],
                "is_signed": False,
                "signed_at": None,
                "pdf_url": None,
                "preview_goals": goals_snapshot,
                "preview_deadlines": deadlines_snapshot,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        contract, _ = CommitmentContract.objects.get_or_create(
            user=request.user,
            defaults={
                "identity_statement": self._default_identity_statement(request.user),
                "signature_name": request.user.email,
            },
        )
        if contract.is_signed:
            return Response(
                {"detail": "Signed contract cannot be modified."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CommitmentContractSerializer(contract, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request):
        sign_serializer = CommitmentContractSignSerializer(data=request.data)
        sign_serializer.is_valid(raise_exception=True)

        contract, _ = CommitmentContract.objects.get_or_create(
            user=request.user,
            defaults={
                "identity_statement": self._default_identity_statement(request.user),
                "signature_name": request.user.email,
            },
        )
        if contract.is_signed:
            return Response(
                {"detail": "Contract already signed and immutable."},
                status=status.HTTP_403_FORBIDDEN,
            )

        goals_snapshot, deadlines_snapshot = build_goal_snapshots(request.user)
        if not goals_snapshot:
            return Response(
                {"detail": "At least one goal is required before signing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        identity_statement = sign_serializer.validated_data["identity_statement"]
        signature_name = sign_serializer.validated_data["signature_name"]
        cc_email = sign_serializer.validated_data.get("cc_email")
        signed_at = timezone.now()
        signed_at_display = signed_at.strftime("%Y-%m-%d %H:%M UTC")

        try:
            pdf_bytes = generate_contract_pdf_bytes(
                user_name=request.user.email,
                signed_at=signed_at_display,
                identity_statement=identity_statement,
                signature_name=signature_name,
                goals_snapshot=goals_snapshot,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Failed to generate contract PDF: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        with transaction.atomic():
            contract.identity_statement = identity_statement
            contract.signature_name = signature_name
            contract.cc_email = cc_email
            contract.goals_snapshot = goals_snapshot
            contract.deadlines_snapshot = deadlines_snapshot
            contract.is_signed = True
            contract.signed_at = signed_at
            contract.pdf_url = f"resend://commitment-contracts/{contract.id}"
            contract.save()

        email_delivery = "sent"
        email_error = None
        try:
            email_html = build_contract_email_html(
                user_name=request.user.email,
                signed_at_display=signed_at_display,
                goals_snapshot=goals_snapshot,
            )
            filename = f"commitment-contract-{request.user.id}.pdf"
            send_contract_email_via_resend(
                to_email=request.user.email,
                cc_email=cc_email,
                subject="Your Signed Roadmap Commitment Contract",
                html_content=email_html,
                attachment_filename=filename,
                attachment_bytes=pdf_bytes,
            )
        except Exception as exc:
            logger.exception("Commitment contract email delivery failed for user %s", request.user.id)
            email_delivery = "failed"
            email_error = str(exc)

        payload = CommitmentContractSerializer(contract).data
        payload["email_delivery"] = email_delivery
        if email_error:
            payload["email_error"] = email_error

        return Response(payload, status=status.HTTP_201_CREATED)

    def delete(self, request):
        contract = CommitmentContract.objects.filter(user=request.user).first()
        if not contract:
            return Response(status=status.HTTP_204_NO_CONTENT)
        if contract.is_signed:
            return Response(
                {"detail": "Signed contract cannot be deleted."},
                status=status.HTTP_403_FORBIDDEN,
            )
        contract.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


    






