from django.shortcuts import render
from .serializers import UserCurrentSituationGoalSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserCurrentSituationGoal, Goal, Milestone, SubGoal, Task
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


class GoalDetailWithHierarchyAPIView(GoalProductionApiView):
    """
    GET API to retrieve a goal with its complete hierarchy:
    Goal → Milestones → SubGoals → Tasks

    Endpoint: GET /api/goals/<goal_id>/hierarchy/

    Features:
    - Optimized queries using select_related and prefetch_related
    - Complete hierarchy in single API call
    - Progress calculations
    - Statistics and analytics
    - User permission checks
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]   
    

    def get(self, request, goal_id):
        try:
            # 1. Fetch Goal with Optimized Queries
            goal = self._get_goal_with_hierarchy(request.user, goal_id)

            if not goal:
                return Response(
                    {"error": "Goal not found or you don't have permission to view it"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 2. Build Complete Response
            response_data = {
                "goal": self._serialize_goal(goal),
                "hierarchy": self._serialize_hierarchy(goal),
                "statistics": self._calculate_statistics(goal),
                "progress": self._calculate_progress(goal),
                "timeline": self._build_timeline(goal),
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"Error fetching goal hierarchy: {str(e)}")
            import traceback

            traceback.print_exc()
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_goal_with_hierarchy(self, user, goal_id):
        """
        Fetch goal with all related data using optimized queries.
        This prevents N+1 query problems.
        """
        try:
            goal = (
                Goal.objects.select_related("attributes")
                .prefetch_related(
                    Prefetch(
                        "milestones",
                        queryset=Milestone.objects.prefetch_related(
                            Prefetch(
                                "subgoals",
                                queryset=SubGoal.objects.prefetch_related(
                                    Prefetch(
                                        "tasks",
                                        queryset=Task.objects.order_by("display_order"),
                                    )
                                ).order_by("display_order"),
                            )
                        ).order_by("display_order"),
                    )
                )
                .get(id=goal_id, user=user)
            )

            return goal

        except Goal.DoesNotExist:
            return None

    def _serialize_goal(self, goal):
        """Serialize goal basic information"""
        return {
            "id": str(goal.id),
            "title": goal.title,
            "description": goal.description,
            "why_it_matters": goal.why_it_matters,
            "primary_category": goal.primary_category,
            "categories": goal.categories,
            "tags": goal.tags,
            "priority": goal.priority,
            "status": goal.status,
            "progress_percentage": goal.progress_percentage,
            "start_date": goal.start_date.isoformat() if goal.start_date else None,
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
            "actual_completion_date": (
                goal.actual_completion_date.isoformat()
                if goal.actual_completion_date
                else None
            ),
            "days_remaining": goal.days_remaining,
            "is_overdue": goal.is_overdue,
            "is_ai_generated": goal.is_ai_generated,
            "ai_feasibility_score": goal.ai_feasibility_score,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "attributes": self._serialize_goal_attributes(goal),
        }

    def _serialize_goal_attributes(self, goal):
        """Serialize goal attributes if they exist"""
        if hasattr(goal, "attributes") and goal.attributes:
            return {
                "financial_data": goal.attributes.financial_data,
                "career_data": goal.attributes.career_data,
                "health_data": goal.attributes.health_data,
                "personal_data": goal.attributes.personal_data,
                "skill_data": goal.attributes.skill_data,
                "custom_data": goal.attributes.custom_data,
            }
        return None

    def _serialize_hierarchy(self, goal):
        """
        Serialize complete hierarchy: Milestones → SubGoals → Tasks
        """
        milestones_data = []

        for milestone in goal.milestones.all():
            milestone_dict = {
                "id": str(milestone.id),
                "title": milestone.title,
                "description": milestone.description,
                "success_criteria": milestone.success_criteria,
                "priority": milestone.priority,
                "status": milestone.status,
                "progress_percentage": milestone.progress_percentage,
                "month_year": milestone.month_year,
                "start_date": (
                    milestone.start_date.isoformat() if milestone.start_date else None
                ),
                "target_date": (
                    milestone.target_date.isoformat() if milestone.target_date else None
                ),
                "completed_date": (
                    milestone.completed_date.isoformat()
                    if milestone.completed_date
                    else None
                ),
                "estimated_duration_days": milestone.estimated_duration_days,
                "display_order": milestone.display_order,
                "is_required": milestone.is_required,
                "is_ai_generated": milestone.is_ai_generated,
                "ai_reasoning": milestone.ai_reasoning,
                "is_user_modified": milestone.is_user_modified,
                "subgoals": [],
            }

            # Add SubGoals
            for subgoal in milestone.subgoals.all():
                subgoal_dict = {
                    "id": str(subgoal.id),
                    "title": subgoal.title,
                    "description": subgoal.description,
                    "learning_objectives": subgoal.learning_objectives,
                    "priority": subgoal.priority,
                    "status": subgoal.status,
                    "progress_percentage": subgoal.progress_percentage,
                    "week_number": subgoal.week_number,
                    "start_date": (
                        subgoal.start_date.isoformat() if subgoal.start_date else None
                    ),
                    "target_date": (
                        subgoal.target_date.isoformat() if subgoal.target_date else None
                    ),
                    "completed_date": (
                        subgoal.completed_date.isoformat()
                        if subgoal.completed_date
                        else None
                    ),
                    "estimated_duration_days": subgoal.estimated_duration_days,
                    "display_order": subgoal.display_order,
                    "is_required": subgoal.is_required,
                    "is_ai_generated": subgoal.is_ai_generated,
                    "ai_reasoning": subgoal.ai_reasoning,
                    "tasks": [],
                }

                # Add Tasks
                for task in subgoal.tasks.all():
                    task_dict = {
                        "id": str(task.id),
                        "title": task.title,
                        "description": task.description,
                        "instructions": task.instructions,
                        "task_type": task.task_type,
                        "resources": task.resources,
                        "priority": task.priority,
                        "status": task.status,
                        "scheduled_date": (
                            task.scheduled_date.isoformat()
                            if task.scheduled_date
                            else None
                        ),
                        "scheduled_time": (
                            task.scheduled_time.isoformat()
                            if task.scheduled_time
                            else None
                        ),
                        "estimated_duration_minutes": task.estimated_duration_minutes,
                        "actual_duration_minutes": task.actual_duration_minutes,
                        "completed_at": (
                            task.completed_at.isoformat() if task.completed_at else None
                        ),
                        "display_order": task.display_order,
                        "is_required": task.is_required,
                        "completion_notes": task.completion_notes,
                        "difficulty_rating": task.difficulty_rating,
                        "is_ai_generated": task.is_ai_generated,
                        "ai_reasoning": task.ai_reasoning,
                    }
                    subgoal_dict["tasks"].append(task_dict)

                milestone_dict["subgoals"].append(subgoal_dict)

            milestones_data.append(milestone_dict)

        return {"milestones": milestones_data, "total_milestones": len(milestones_data)}

    def _calculate_statistics(self, goal):
        """Calculate statistics for the goal"""
        milestones = goal.milestones.all()
        total_milestones = milestones.count()

        # Milestone stats
        milestones_completed = milestones.filter(status="completed").count()
        milestones_in_progress = milestones.filter(status="in_progress").count()
        milestones_not_started = milestones.filter(status="not_started").count()

        # SubGoal stats
        total_subgoals = 0
        subgoals_completed = 0
        subgoals_in_progress = 0

        # Task stats
        total_tasks = 0
        tasks_completed = 0
        tasks_in_progress = 0
        tasks_pending = 0

        for milestone in milestones:
            subgoals = milestone.subgoals.all()
            total_subgoals += subgoals.count()
            subgoals_completed += subgoals.filter(status="completed").count()
            subgoals_in_progress += subgoals.filter(status="in_progress").count()

            for subgoal in subgoals:
                tasks = subgoal.tasks.all()
                total_tasks += tasks.count()
                tasks_completed += tasks.filter(status="completed").count()
                tasks_in_progress += tasks.filter(status="in_progress").count()
                tasks_pending += tasks.filter(status="pending").count()

        # Calculate average difficulty
        all_tasks = Task.objects.filter(
            subgoal__milestone__goal=goal, difficulty_rating__isnull=False
        )
        avg_difficulty = all_tasks.aggregate(avg=Avg("difficulty_rating"))["avg"] or 0

        # Calculate total time
        total_estimated_time = (
            Task.objects.filter(subgoal__milestone__goal=goal).aggregate(
                total=Sum("estimated_duration_minutes")
            )["total"]
            or 0
        )

        total_actual_time = (
            Task.objects.filter(
                subgoal__milestone__goal=goal, actual_duration_minutes__isnull=False
            ).aggregate(total=Sum("actual_duration_minutes"))["total"]
            or 0
        )

        return {
            "milestones": {
                "total": total_milestones,
                "completed": milestones_completed,
                "in_progress": milestones_in_progress,
                "not_started": milestones_not_started,
                "completion_rate": (
                    round((milestones_completed / total_milestones * 100), 2)
                    if total_milestones > 0
                    else 0
                ),
            },
            "subgoals": {
                "total": total_subgoals,
                "completed": subgoals_completed,
                "in_progress": subgoals_in_progress,
                "pending": total_subgoals - subgoals_completed - subgoals_in_progress,
                "completion_rate": (
                    round((subgoals_completed / total_subgoals * 100), 2)
                    if total_subgoals > 0
                    else 0
                ),
            },
            "tasks": {
                "total": total_tasks,
                "completed": tasks_completed,
                "in_progress": tasks_in_progress,
                "pending": tasks_pending,
                "completion_rate": (
                    round((tasks_completed / total_tasks * 100), 2)
                    if total_tasks > 0
                    else 0
                ),
            },
            "time": {
                "total_estimated_hours": round(total_estimated_time / 60, 2),
                "total_actual_hours": round(total_actual_time / 60, 2),
                "time_efficiency": (
                    round((total_actual_time / total_estimated_time * 100), 2)
                    if total_estimated_time > 0
                    else 0
                ),
            },
            "difficulty": {"average_rating": round(avg_difficulty, 2)},
        }

    def _calculate_progress(self, goal):
        """Calculate detailed progress information"""
        today = timezone.now().date()

        # Overall progress
        overall_progress = goal.progress_percentage

        # Current milestone
        current_milestone = (
            goal.milestones.filter(status="in_progress").first()
            or goal.milestones.filter(status="not_started")
            .order_by("display_order")
            .first()
        )

        current_milestone_data = None
        if current_milestone:
            current_milestone_data = {
                "id": str(current_milestone.id),
                "title": current_milestone.title,
                "progress": current_milestone.progress_percentage,
                "status": current_milestone.status,
            }

        # Current week (subgoal)
        current_subgoal = None
        if current_milestone:
            current_subgoal = (
                current_milestone.subgoals.filter(status="in_progress").first()
                or current_milestone.subgoals.filter(status="pending")
                .order_by("display_order")
                .first()
            )

        current_week_data = None
        if current_subgoal:
            current_week_data = {
                "id": str(current_subgoal.id),
                "title": current_subgoal.title,
                "week_number": current_subgoal.week_number,
                "progress": current_subgoal.progress_percentage,
                "status": current_subgoal.status,
            }

        # Today's tasks
        todays_tasks = []
        if current_subgoal:
            tasks = current_subgoal.tasks.filter(
                Q(scheduled_date=today)
                | Q(scheduled_date__isnull=True, status="pending")
            ).order_by("display_order")[
                :5
            ]  # Limit to 5

            todays_tasks = [
                {
                    "id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                    "estimated_duration_minutes": task.estimated_duration_minutes,
                    "priority": task.priority,
                }
                for task in tasks
            ]

        # Streak calculation (tasks completed consecutively)
        recent_tasks = Task.objects.filter(
            subgoal__milestone__goal=goal,
            status="completed",
            completed_at__isnull=False,
        ).order_by("-completed_at")[:30]

        current_streak = 0
        if recent_tasks:
            last_date = recent_tasks[0].completed_at.date()
            for task in recent_tasks:
                task_date = task.completed_at.date()
                if (last_date - task_date).days <= 1:
                    current_streak += 1
                    last_date = task_date
                else:
                    break

        return {
            "overall_progress": overall_progress,
            "current_milestone": current_milestone_data,
            "current_week": current_week_data,
            "todays_tasks": todays_tasks,
            "streak": {"current": current_streak, "unit": "days"},
            "on_track": self._is_on_track(goal),
        }

    def _is_on_track(self, goal):
        """Determine if user is on track to meet goal"""
        if not goal.target_date:
            return None

        today = timezone.now().date()
        total_days = (goal.target_date - goal.start_date).days
        elapsed_days = (today - goal.start_date).days

        if total_days <= 0:
            return None

        expected_progress = (elapsed_days / total_days) * 100
        actual_progress = goal.progress_percentage

        return {
            "is_on_track": actual_progress >= expected_progress - 10,  # 10% buffer
            "expected_progress": round(expected_progress, 2),
            "actual_progress": actual_progress,
            "difference": round(actual_progress - expected_progress, 2),
        }

    def _build_timeline(self, goal):
        """Build a timeline view of the goal"""
        timeline = []

        for milestone in goal.milestones.all().order_by("display_order"):
            milestone_entry = {
                "type": "milestone",
                "id": str(milestone.id),
                "title": milestone.title,
                "month": milestone.month_year,
                "status": milestone.status,
                "start_date": (
                    milestone.start_date.isoformat() if milestone.start_date else None
                ),
                "target_date": (
                    milestone.target_date.isoformat() if milestone.target_date else None
                ),
                "weeks": [],
            }

            for subgoal in milestone.subgoals.all().order_by("display_order"):
                week_entry = {
                    "type": "week",
                    "id": str(subgoal.id),
                    "title": subgoal.title,
                    "week_number": subgoal.week_number,
                    "status": subgoal.status,
                    "task_count": subgoal.tasks.count(),
                    "completed_tasks": subgoal.tasks.filter(status="completed").count(),
                }
                milestone_entry["weeks"].append(week_entry)

            timeline.append(milestone_entry)

        return timeline


# ==============================================================================
# ALTERNATIVE: Lightweight Version (Faster, Less Data)
# ==============================================================================


class GoalDetailLightweightAPIView(APIView):
    """
    Lightweight version that returns only basic info and counts.
    Use this for list views or when you don't need all the details.

    Endpoint: GET /api/goals/<goal_id>/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        try:
            goal = Goal.objects.annotate(
                milestone_count=Count("milestones"),
                completed_milestones=Count(
                    "milestones", filter=Q(milestones__status="completed")
                ),
            ).get(id=goal_id, user=request.user)

            return Response(
                {
                    "id": str(goal.id),
                    "title": goal.title,
                    "description": goal.description,
                    "status": goal.status,
                    "progress_percentage": goal.progress_percentage,
                    "priority": goal.priority,
                    "primary_category": goal.primary_category,
                    "target_date": (
                        goal.target_date.isoformat() if goal.target_date else None
                    ),
                    "days_remaining": goal.days_remaining,
                    "is_overdue": goal.is_overdue,
                    "counts": {
                        "milestones": goal.milestone_count,
                        "completed_milestones": goal.completed_milestones,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Goal.DoesNotExist:
            return Response(
                {"error": "Goal not found"}, status=status.HTTP_404_NOT_FOUND
            )


# ==============================================================================
# BONUS: List All Goals (Summary View)
# ==============================================================================


class GoalListAPIView(APIView):
    """
    List all goals for the authenticated user with summary data.

    Endpoint: GET /api/goals/
    Query Params:
    - status: Filter by status (not_started, in_progress, completed)
    - category: Filter by category (financial, career, health, personal)
    - priority: Filter by priority (low, medium, high)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Start with user's goals
            goals = Goal.objects.filter(user=request.user)

            # Apply filters
            status_filter = request.query_params.get("status")
            if status_filter:
                goals = goals.filter(status=status_filter)

            category_filter = request.query_params.get("category")
            if category_filter:
                goals = goals.filter(primary_category=category_filter)

            priority_filter = request.query_params.get("priority")
            if priority_filter:
                goals = goals.filter(priority=priority_filter)

            # Annotate with counts
            goals = goals.annotate(
                milestone_count=Count("milestones"),
                completed_milestones=Count(
                    "milestones", filter=Q(milestones__status="completed")
                ),
                total_tasks=Count("milestones__subgoals__tasks"),
                completed_tasks=Count(
                    "milestones__subgoals__tasks",
                    filter=Q(milestones__subgoals__tasks__status="completed"),
                ),
            ).order_by("-priority", "target_date")

            # Serialize
            goals_data = []
            for goal in goals:
                goals_data.append(
                    {
                        "id": str(goal.id),
                        "title": goal.title,
                        "description": (
                            goal.description[:100] + "..."
                            if len(goal.description) > 100
                            else goal.description
                        ),
                        "status": goal.status,
                        "progress_percentage": goal.progress_percentage,
                        "priority": goal.priority,
                        "primary_category": goal.primary_category,
                        "categories": goal.categories,
                        "target_date": (
                            goal.target_date.isoformat() if goal.target_date else None
                        ),
                        "days_remaining": goal.days_remaining,
                        "is_overdue": goal.is_overdue,
                        "counts": {
                            "milestones": goal.milestone_count,
                            "completed_milestones": goal.completed_milestones,
                            "total_tasks": goal.total_tasks,
                            "completed_tasks": goal.completed_tasks,
                        },
                    }
                )

            return Response(
                {"count": len(goals_data), "goals": goals_data},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            print(f"Error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
