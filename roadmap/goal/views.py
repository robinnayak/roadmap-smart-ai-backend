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
from .serializers import UserCurrentSituationGoalSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserCurrentSituationGoal, Goal, Milestone, SubGoal, Task, GoalAttributes
from .serializers import (
    GoalSerializer,
    GoalListSerializer,
    MilestoneSerializer,
    SubGoalSerializer,
    TaskSerializer,
)
from django.utils import timezone
from ai.models import AIProcessingJob
from ai.services.text_extraction import GoalAttributeExtractor
from ai.services.GoalHierarchyGenerator import GoalHierarchyGenerator
from rest_framework import status
import json
from authentication.models import UserPersonalDetails
from django.db.models import Prefetch, Count, Avg, Q, Sum
from rest_framework.throttling import UserRateThrottle
import logging

from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework.exceptions import NotFound, ValidationError
from goal.core.response import success_response, error_response, created_response


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
        # FIX: filter() never raises DoesNotExist — removed the dead try/except
        goals = Goal.objects.filter(user=request.user).prefetch_related(
            "milestones", "attributes"
        )

        detailed = request.query_params.get("detailed", "false").lower() == "true"
        serializer_class = GoalSerializer if detailed else GoalListSerializer
        serializer = serializer_class(goals, many=True)

        return Response(
            {"count": goals.count(), "goals": serializer.data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        """
        Create a new goal with optional attribute extraction.
        """
        try:
            print(f"POST Goal API Called")
            print(f"Request data: {request.data}")

            data = request.data.copy()

            # Add default values if not provided
            if "start_date" not in data:
                data["start_date"] = timezone.localdate()

            # if 'progress_percentage' not in data:
            #     data['progress_percentage'] = 0

            # Ensure categories is a list if provided
            # if 'categories' in data and isinstance(data['categories'], str):
            #     try:
            #         data['categories'] = json.loads(data['categories'])
            #     except:
            #         # If it's a comma-separated string, convert to list
            #         data['categories'] = [cat.strip() for cat in data['categories'].split(',')]
            data.pop("categories", None)
            data.pop("tags", None)
            # Create serializer
            serializer = GoalSerializer(data=data, context={"request": request})

            if serializer.is_valid():
                print(f"Serializer valid, saving goal...")
                # Save goal with current user
                goal = serializer.save(user=request.user)

                # Get goal attributes input
                # goal_attributes_input = data.get('goal_attributes_input')

                # Create response data
                response_data = {
                    "message": "Goal created successfully!",
                    "goal": GoalSerializer(goal).data,
                    # "attributes_extracted": bool(goal_attributes_input)
                }

                print(f"Goal created: {goal.id}")
                return Response(response_data, status=status.HTTP_201_CREATED)
            else:
                print(f"Serializer errors: {serializer.errors}")
                return Response(
                    {"message": "Validation failed", "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            import traceback

            traceback.print_exc()
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GoalDetailAPIView(APIView):
    """View to handle single goal operations (GET, PUT, DELETE)"""

    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        """Get a single goal by ID"""
        try:
            # Try to find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check if the goal belongs to the current user
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to view this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Convert goal to JSON format
            serializer = GoalSerializer(goal)

            # Return the goal data
            return Response(
                {"message": "Goal retrieved successfully", "goal": serializer.data},
                status=status.HTTP_200_OK,
            )

        except Goal.DoesNotExist:
            # Goal not found
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            # Any other error
            import traceback

            traceback.print_exc()
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, goal_id):
        """Update a goal completely (all fields must be provided)"""
        try:
            # Find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check ownership
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to update this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Get new data from request
            data = request.data

            # Update the goal with new data
            serializer = GoalSerializer(goal, data=data)

            # Check if data is valid
            if serializer.is_valid():
                # Save the updated goal
                updated_goal = serializer.save()

                return Response(
                    {"message": "Goal updated successfully", "goal": serializer.data},
                    status=status.HTTP_200_OK,
                )
            else:
                # Return validation errors
                return Response(
                    {"message": "Validation failed", "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, goal_id):
        """Delete a goal"""
        try:
            # Find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check ownership
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to delete this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Delete the goal
            goal.delete()

            return Response(
                {"message": f"Goal '{goal.title}' deleted successfully"},
                status=status.HTTP_200_OK,
            )

        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
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

    def post(self, request):
        try:
            print(f"\n{'='*80}")
            print(f"CREATE GOAL WITH HIERARCHY API Called")
            print(f"{'='*80}\n")

            # 1. Create Goal
            data = request.data.copy()
            # Default start_date if not provided
            if "start_date" not in data:
                data["start_date"] = timezone.localdate()

            data.pop("categories", None)
            data.pop("tags", None)

            serializer = GoalSerializer(data=data, context={"request": request})
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            goal = serializer.save(user=request.user)
            logger.info(f"Goal created: {goal.id} - {goal.title}")
            print(f"✓ Goal created: {goal.id} - {goal.title}")

            goal_data = {
                "title": goal.title,
                "description": goal.description,
                "why_it_matters": goal.why_it_matters,
                "primary_category": goal.primary_category,
                "impact_dimensions": goal.impact_dimensions,
                "start_date": goal.start_date,
                "target_date": goal.target_date,
            }
            # Get user context
            user_context = self._get_user_context(request.user)
            # 2. Generate Complete Hierarchy
            generator = GoalHierarchyGenerator()

            hierarchy_result = generator.generate_complete_hierarchy(
                goal_data=goal_data,
                user=request.user,
                user_context=user_context,
            )


            if hierarchy_result.get("status") != "success":
                logger.warning(
                    "Hierarchy generation failed for goal %s: %s",
                    goal.id,
                    hierarchy_result.get("message"),
                )
                return Response(
                    {
                        "message": "Goal created, but hierarchy generation failed.",
                        "goal": GoalSerializer(goal).data,
                        "error": hierarchy_result.get("message"),
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
        print(f"\n📊 SAVING HIERARCHY TO DATABASE")
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
        # Merge instructions into description if the AI still sends both
        description = data.get("description", "")
        instructions = data.get("instructions", "")
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
            is_ai_generated=True,
            ai_reasoning=data.get("reasoning", data.get("ai_reasoning", "")),
        )
        
        
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

    Returns complete hierarchy: milestones → subgoals → tasks.
    Full task details are now included for each subgoal.

    This is what powers the "Action Plan" expansion in your UI screenshot.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        try:
            goal = (
                Goal.objects.prefetch_related(
                    "milestones__subgoals__tasks",
                )
                .select_related("attributes")
                .get(id=goal_id, user=request.user)
            )
        except Goal.DoesNotExist:
            return Response(
                {"error": "Goal not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        today = timezone.localdate()

        # --- Goal summary (header of the expanded card) ----------------------
        goal_data = {
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
            "days_remaining":      goal.days_remaining,
            "is_overdue":          goal.is_overdue,
            "is_ai_generated":     goal.is_ai_generated,
            "ai_feasibility_score": goal.ai_feasibility_score,
        }

        # --- On-track calculation (powers the progress indicator) ------------
        on_track = None
        if goal.start_date and goal.target_date:
            total_days   = (goal.target_date - goal.start_date).days
            elapsed_days = (today - goal.start_date).days
            if total_days > 0:
                expected = round((elapsed_days / total_days) * 100, 1)
                actual   = goal.progress_percentage
                on_track = {
                    "is_on_track":        actual >= expected - 10,  # 10% buffer
                    "expected_progress":  expected,
                    "actual_progress":    actual,
                    "difference":         round(actual - expected, 1),
                }

        # --- Milestones + SubGoals (the hierarchy shown in the UI) -----------
        milestones_data = []
        for milestone in goal.milestones.all().order_by("display_order"):
            subgoals_data = []

            for subgoal in milestone.subgoals.all().order_by("display_order"):
                # Build full tasks list with all details
                tasks_data = []
                for task in subgoal.tasks.all().order_by("display_order"):
                    tasks_data.append({
                        "id":                         str(task.id),
                        "title":                      task.title,
                        "description":                task.description,
                        "task_type":                  task.task_type,
                        "priority":                   task.priority,
                        "status":                     task.status,
                        "display_order":              task.display_order,
                        "estimated_duration_minutes": task.estimated_duration_minutes,
                        "actual_duration_minutes":    task.actual_duration_minutes,
                        "scheduled_date":             task.scheduled_date.isoformat() if task.scheduled_date else None,
                        "completed_at":               task.completed_at.isoformat() if task.completed_at else None,
                        "is_ai_generated":            task.is_ai_generated,
                    })

                # Calculate task counts from the tasks_data list
                total_tasks     = len(tasks_data)
                completed_tasks = sum(1 for t in tasks_data if t["status"] == "completed")

                subgoals_data.append({
                    "id":                  str(subgoal.id),
                    "title":               subgoal.title,
                    "description":         subgoal.description,
                    "priority":            subgoal.priority,
                    "status":              subgoal.status,
                    "progress_percentage": subgoal.progress_percentage,
                    "week_number":         subgoal.week_number,  # @property
                    "display_order":       subgoal.display_order,
                    "start_date":          subgoal.start_date.isoformat() if subgoal.start_date else None,
                    "target_date":         subgoal.target_date.isoformat() if subgoal.target_date else None,
                    "completed_date":      subgoal.completed_date.isoformat() if subgoal.completed_date else None,
                    "is_ai_generated":     subgoal.is_ai_generated,
                    "tasks":               tasks_data,
                    "task_counts": {
                        "total":     total_tasks,
                        "completed": completed_tasks,
                        "pending":   total_tasks - completed_tasks,
                    },
                })

            milestones_data.append({
                "id":                  str(milestone.id),
                "title":               milestone.title,
                "description":         milestone.description,
                "success_criteria":    milestone.success_criteria,
                "priority":            milestone.priority,
                "status":              milestone.status,
                "progress_percentage": milestone.progress_percentage,
                "display_order":       milestone.display_order,
                "start_date":          milestone.start_date.isoformat() if milestone.start_date else None,
                "target_date":         milestone.target_date.isoformat() if milestone.target_date else None,
                "completed_date":      milestone.completed_date.isoformat() if milestone.completed_date else None,
                "is_ai_generated":     milestone.is_ai_generated,
                "subgoals":            subgoals_data,
                "subgoal_count":       len(subgoals_data),
            })

        # --- Aggregate stats (drives the statistics panel) -------------------
        all_milestones  = goal.milestones.all()
        total_m         = all_milestones.count()
        completed_m     = all_milestones.filter(status="completed").count()

        # Single query across all subgoals and tasks for this goal
        all_subgoals    = SubGoal.objects.filter(milestone__goal=goal)
        total_sg        = all_subgoals.count()
        completed_sg    = all_subgoals.filter(status="completed").count()

        from goal.models import Task
        from django.db.models import Sum, Avg
        all_tasks       = Task.objects.filter(subgoal__milestone__goal=goal)
        total_t         = all_tasks.count()
        completed_t     = all_tasks.filter(status="completed").count()
        est_minutes     = all_tasks.aggregate(s=Sum("estimated_duration_minutes"))["s"] or 0
        actual_minutes  = all_tasks.filter(actual_duration_minutes__isnull=False).aggregate(
            s=Sum("actual_duration_minutes")
        )["s"] or 0

        stats = {
            "milestones": {
                "total":           total_m,
                "completed":       completed_m,
                "completion_rate": round(completed_m / total_m * 100, 1) if total_m else 0,
            },
            "subgoals": {
                "total":           total_sg,
                "completed":       completed_sg,
                "completion_rate": round(completed_sg / total_sg * 100, 1) if total_sg else 0,
            },
            "tasks": {
                "total":           total_t,
                "completed":       completed_t,
                "completion_rate": round(completed_t / total_t * 100, 1) if total_t else 0,
            },
            "time": {
                "estimated_hours": round(est_minutes / 60, 1),
                "actual_hours":    round(actual_minutes / 60, 1),
            },
        }

        return Response(
            {
                "goal":       goal_data,
                "on_track":   on_track,
                "milestones": milestones_data,
                "stats":      stats,
            },
            status=status.HTTP_200_OK,
        )
        


class GoalDetailAPIView(APIView):
    """
    PATCH  /api/goals/<goal_id>/   → partial update (title, priority, target_date, etc.)
    DELETE /api/goals/<goal_id>/   → delete goal and all children (CASCADE)
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, goal_id):
        try:
            goal = Goal.objects.get(id=goal_id, user=request.user)
        except Goal.DoesNotExist:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, goal_id):
        try:
            goal = Goal.objects.get(id=goal_id, user=request.user)
        except Goal.DoesNotExist:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        goal.delete()  # CASCADE deletes Milestones → SubGoals → Tasks automatically
        return Response(status=status.HTTP_204_NO_CONTENT)
    


class TaskDetailApiView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]
    def _get_task(self, task_id):
        try:
            return get_object_or_404(Task, id=task_id)
        except Task.DoesNotExist:
            return None

    
    def get(self, request, task_id):
        task = self._get_task(task_id)
        if not task:
            return Response({"error": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, task_id):
        task = self._get_task(task_id)
        
        if not task:
            return Response({"error": "Task not found."})
        
        serializer = TaskSerializer(task, data=request.data, partial=True)
        try:
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as err:
            return Response({"error": str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    
    def delete(self, request, task_id):
        task = self._get_task(task_id)
        if not task:
            return Response({"error": "Task not found."})
        task.delete()
        return Response({"message": "Task deleted successfully."},status=status.HTTP_204_NO_CONTENT)


    