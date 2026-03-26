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
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from .models import (
    UserCurrentSituationGoal,
    Goal,
    GoalCommitmentRecord,
    Milestone,
    SubGoal,
    Task,
    GoalAttributes,
    CommitmentContract,
    UserFinancialProfile,
    GoalLink,
    FinancialProgressEntry,
)
from .serializers import (
    GoalSerializer,
    GoalListSerializer,
    MilestoneSerializer,
    SubGoalSerializer,
    TaskSerializer,
    CommitmentContractSerializer,
    CommitmentContractSignSerializer,
    GoalCommitmentRecordReadSerializer,
    UserFinancialProfileSerializer,
    FinancialFeasibilitySerializer,
    GoalLinkSerializer,
    FinancialProgressEntrySerializer,
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
from django.db import close_old_connections, IntegrityError
from django.db import transaction
from django.http import Http404
from rest_framework.throttling import UserRateThrottle
import logging
from decimal import Decimal, ROUND_CEILING

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
from goal.services.contract_template import GoalContractTemplateService
from goal.services.goal_domain import (
    build_goal_hierarchy_payload,
    build_goal_seed_data,
    create_goal_for_user,
    evaluate_financial_goal_feasibility,
    get_goal_with_hierarchy_for_user,
    get_user_goals_payload,
)
from goal.services.category_resolver import GOAL_CATEGORIES
from goal.services.category_resolver import (
    get_goal_attribute_bucket,
    normalize_goal_category_for_query,
)
from goal.services.category_pillars import canonical_to_pillar
from goal.services.financial_intelligence import (
    calculate_feasibility,
    evaluate_profile_review_for_goal,
    evaluate_profile_review_for_user,
    mark_profile_review_needed,
    build_profile_plan_hint,
    build_financial_plan_summary,
)
from goal.services.timeline_insight_contract import (
    TimelineInsightBoundaryError,
    assert_read_only_timeline_insight_request,
)
from goal.services.timeline_insight_service import GoalTimelineInsightService
from goal.services.timeline_overview_insight_service import TimelineOverviewInsightService
from goal.services.illustration_service import (
    ALLOWED_ILLUSTRATION_CONTENT_TYPES,
    MAX_ILLUSTRATION_SIZE_BYTES,
    clear_goal_illustration,
    save_goal_illustration,
)
from ai.utils.validators import normalize_task_type


logger = logging.getLogger(__name__)
# Create your views here.

# Priority sort order used in Python (CharField can't sort high>medium>low in DB)
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _get_profile_review_state(user):
    profile = UserFinancialProfile.objects.filter(user=user).first()
    return {
        "needs_profile_review": bool(profile and profile.needs_review),
        "review_reason": profile.review_reason if profile else "",
    }


def _build_illustration_response(goal):
    message_by_status = {
        "pending": "No illustration uploaded yet.",
        "done": "Illustration uploaded.",
    }
    payload = {
        "status": goal.illustration_status,
        "illustration_url": goal.illustration_url,
        "message": message_by_status.get(goal.illustration_status, "Illustration status updated."),
    }
    if get_ai_debug_enabled():
        payload["debug"] = {
            "goal_id": str(goal.id),
            "has_url": bool(goal.illustration_url),
            "generated_at": goal.illustration_generated_at.isoformat() if goal.illustration_generated_at else None,
        }
    return payload


def _build_public_illustration_url_for_request(request, illustration_url):
    if not illustration_url or not illustration_url.startswith("/"):
        return illustration_url
    return request.build_absolute_uri(illustration_url)




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
# Financial Profile API
# =======================


class FinancialProfileAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = UserFinancialProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {
                    "exists": False,
                    "profile": None,
                    "needs_profile_review": False,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "exists": True,
                "profile": UserFinancialProfileSerializer(profile).data,
                "needs_profile_review": bool(profile.needs_review),
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        if UserFinancialProfile.objects.filter(user=request.user).exists():
            return Response(
                {
                    "error": "validation_error",
                    "details": {
                        "profile": ["Financial profile already exists. Use PATCH to update."]
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserFinancialProfileSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = serializer.save(user=request.user, needs_review=False, review_reason="")
        return Response(
            {
                "profile": UserFinancialProfileSerializer(profile).data,
                "needs_profile_review": bool(profile.needs_review),
            },
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request):
        profile = UserFinancialProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {
                    "error": "validation_error",
                    "details": {
                        "profile": ["Financial profile does not exist. Create it first."]
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserFinancialProfileSerializer(profile, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        situation_changed = bool(serializer.validated_data.pop("situation_changed", False))
        updated_fields = list(serializer.validated_data.keys())
        has_content_updates = bool(updated_fields)

        for field, value in serializer.validated_data.items():
            setattr(profile, field, value)

        # Contract rule: profile field updates clear stale state by default.
        if has_content_updates:
            profile.needs_review = False
            profile.review_reason = ""

        if has_content_updates or situation_changed:
            needs_review, review_reason = evaluate_profile_review_for_user(user=request.user)
            if needs_review:
                profile.needs_review = True
                profile.review_reason = review_reason[:255]

        profile.save()
        return Response(
            {
                "profile": UserFinancialProfileSerializer(profile).data,
                "needs_profile_review": bool(profile.needs_review),
            },
            status=status.HTTP_200_OK,
        )


class FinancialFeasibilityAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = UserFinancialProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {
                    "error": "validation_error",
                    "details": {
                        "financial_profile": [
                            "Complete your financial profile before running feasibility."
                        ]
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = FinancialFeasibilitySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data
        result = calculate_feasibility(
            target_amount=validated["target_amount"],
            current_saved=validated["current_saved"],
            target_date=validated["target_date"],
            surplus_range=profile.monthly_surplus_range,
            today=timezone.localdate(),
        )

        return Response(
            {
                "feasibility_status": result.feasibility_status,
                "gap_amount": float(result.gap_amount),
                "months_remaining": result.months_remaining,
                "required_monthly_savings": float(result.required_monthly_savings),
                "available_monthly_surplus": float(result.available_monthly_surplus),
                "message": result.message,
                "adjustments": {
                    "suggested_target_date": (
                        result.suggested_target_date.isoformat()
                        if result.suggested_target_date
                        else None
                    ),
                    "achievable_amount_by_original_date": float(
                        result.achievable_amount_by_original_date
                    ),
                },
                "needs_profile_review": bool(profile.needs_review),
            },
            status=status.HTTP_200_OK,
        )


class GoalLinkAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def _get_owned_goal(self, user, goal_id):
        return get_object_or_404(Goal, id=goal_id, user=user)

    def get(self, request, goal_id):
        goal = self._get_owned_goal(request.user, goal_id)
        direction = request.query_params.get("direction", "source")

        if direction == "contributing":
            links = GoalLink.objects.filter(contributing_goal=goal).select_related(
                "source_goal",
                "contributing_goal",
            )
            root_payload = {
                "source_goal_id": None,
                "contributing_goal_id": str(goal.id),
            }
        else:
            links = GoalLink.objects.filter(source_goal=goal).select_related(
                "source_goal",
                "contributing_goal",
            )
            root_payload = {
                "source_goal_id": str(goal.id),
                "contributing_goal_id": None,
            }

        profile_review_state = _get_profile_review_state(request.user)
        return Response(
            {
                **root_payload,
                "links": GoalLinkSerializer(links, many=True).data,
                "needs_profile_review": profile_review_state["needs_profile_review"],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, goal_id):
        source_goal = self._get_owned_goal(request.user, goal_id)
        serializer = GoalLinkSerializer(
            data=request.data,
            context={"source_goal": source_goal},
        )
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            link = serializer.save(source_goal=source_goal)
        except IntegrityError:
            return Response(
                {
                    "error": "validation_error",
                    "details": {"link": ["This goal link already exists."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(GoalLinkSerializer(link).data, status=status.HTTP_201_CREATED)


class GoalLinkDetailAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, goal_id, link_id):
        source_goal = get_object_or_404(Goal, id=goal_id, user=request.user)
        link = get_object_or_404(
            GoalLink.objects.select_related("source_goal"),
            id=link_id,
            source_goal=source_goal,
        )
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FinancialProgressAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _add_months(month_anchor, offset: int):
        year_delta, month_index = divmod((month_anchor.month - 1) + offset, 12)
        return month_anchor.replace(year=month_anchor.year + year_delta, month=month_index + 1, day=1)

    def _get_goal(self, user, goal_id):
        return get_object_or_404(Goal, id=goal_id, user=user, primary_category="finance")

    def _recompute_running_totals(self, goal: Goal):
        entries = FinancialProgressEntry.objects.filter(goal=goal).order_by("month", "created_at")
        running_total = Decimal(goal.financial_current_saved or 0)
        for entry in entries:
            running_total += Decimal(entry.actual_savings or 0)
            running_total = running_total.quantize(Decimal("0.01"))
            if entry.running_total_saved != running_total:
                entry.running_total_saved = running_total
                entry.save(update_fields=["running_total_saved", "updated_at"])
        return list(entries)

    def _build_summary(self, goal: Goal, entries):
        target_amount = Decimal(goal.financial_target_amount or 0).quantize(Decimal("0.01"))
        running_total = (
            Decimal(entries[-1].running_total_saved).quantize(Decimal("0.01"))
            if entries
            else Decimal(goal.financial_current_saved or 0).quantize(Decimal("0.01"))
        )
        remaining_amount = max(Decimal("0.00"), target_amount - running_total).quantize(Decimal("0.01"))

        if running_total >= target_amount and target_amount > 0:
            return {
                "running_total_saved": float(running_total),
                "target_amount": float(target_amount),
                "remaining_amount": float(remaining_amount),
                "projected_completion_date": timezone.localdate().replace(day=1).isoformat(),
                "projection_status": "completed",
            }

        if entries:
            months_count = Decimal(len(entries))
            total_actual = sum((Decimal(entry.actual_savings or 0) for entry in entries), Decimal("0"))
            monthly_rate = (total_actual / months_count).quantize(Decimal("0.01")) if months_count else Decimal("0.00")
        else:
            monthly_rate = Decimal(goal.financial_required_monthly_savings or 0).quantize(Decimal("0.01"))

        projected_completion_date = None
        projection_status = "behind"

        if monthly_rate > 0 and remaining_amount > 0:
            months_needed = int((remaining_amount / monthly_rate).to_integral_value(rounding=ROUND_CEILING))
            months_needed = max(1, months_needed)
            projected_date = self._add_months(timezone.localdate().replace(day=1), months_needed)
            projected_completion_date = projected_date.isoformat()

            if goal.target_date:
                target_month = goal.target_date.replace(day=1)
                if projected_date < target_month:
                    projection_status = "ahead"
                elif projected_date == target_month:
                    projection_status = "on_track"
                else:
                    projection_status = "behind"

        return {
            "running_total_saved": float(running_total),
            "target_amount": float(target_amount),
            "remaining_amount": float(remaining_amount),
            "projected_completion_date": projected_completion_date,
            "projection_status": projection_status,
        }

    def get(self, request, goal_id):
        goal = self._get_goal(request.user, goal_id)
        entries = self._recompute_running_totals(goal)
        summary = self._build_summary(goal, entries)
        return Response(
            {
                "goal_id": str(goal.id),
                "entries": FinancialProgressEntrySerializer(entries, many=True).data,
                "summary": summary,
                "needs_profile_review": _get_profile_review_state(request.user)["needs_profile_review"],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, goal_id):
        goal = self._get_goal(request.user, goal_id)
        serializer = FinancialProgressEntrySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "validation_error", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data
        entry, _ = FinancialProgressEntry.objects.update_or_create(
            goal=goal,
            month=validated["month"],
            defaults={
                "user": request.user,
                "planned_savings": validated["planned_savings"],
                "actual_savings": validated["actual_savings"],
                "notes": validated.get("notes", ""),
            },
        )
        if entry.user_id != request.user.id:
            entry.user = request.user
            entry.save(update_fields=["user", "updated_at"])

        entries = self._recompute_running_totals(goal)
        summary = self._build_summary(goal, entries)
        return Response(
            {
                "goal_id": str(goal.id),
                "entries": FinancialProgressEntrySerializer(entries, many=True).data,
                "summary": summary,
                "needs_profile_review": _get_profile_review_state(request.user)["needs_profile_review"],
            },
            status=status.HTTP_200_OK,
        )


# =======================
# # Create Goal API View Here GET and POST
# =======================





class GoalAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _validation_error_response(errors):
        return Response(
            {
                "error": "validation_error",
                "code": "validation_error",
                "details": errors,
                "status": status.HTTP_400_BAD_REQUEST,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

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
                if "financial_feasibility" in errors:
                    return Response(errors, status=status.HTTP_400_BAD_REQUEST)
                if isinstance(errors, dict) and "error" in errors and "code" in errors and "status" in errors:
                    return Response(errors, status=errors.get("status", status.HTTP_400_BAD_REQUEST))
                return self._validation_error_response(errors)

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

    @staticmethod
    def _validation_error_response(errors):
        return Response(
            {
                "error": "validation_error",
                "code": "validation_error",
                "details": errors,
                "status": status.HTTP_400_BAD_REQUEST,
            },
            status=status.HTTP_400_BAD_REQUEST,
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
                if isinstance(errors, dict) and "error" in errors and "code" in errors and "status" in errors:
                    return Response(errors, status=errors.get("status", status.HTTP_400_BAD_REQUEST))
                return self._validation_error_response(errors)

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
                def _start_async_worker_after_commit():
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

                transaction.on_commit(_start_async_worker_after_commit)

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
            financial_extension = self._build_financial_extension(goal=goal, user=request.user)
            # Get user context
            user_context = self._get_user_context(request.user)
            if missing_ai_env_vars:
                return Response(
                    {
                        "message": "Goal created, but hierarchy generation is unavailable until AI runtime is configured.",
                        "goal": GoalSerializer(goal).data,
                        "error": ai_runtime_error_message,
                        **financial_extension,
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
                        **financial_extension,
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
                    **financial_extension,
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

    def _build_financial_extension(self, *, goal: Goal, user) -> dict:
        summary = build_financial_plan_summary(goal=goal, user=user)
        if not summary:
            return {}
        profile_state = _get_profile_review_state(user)
        return {
            "financial_plan_summary": summary,
            "needs_profile_review": profile_state["needs_profile_review"],
        }

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

        goal = subgoal.milestone.goal
        resolved_category = goal.primary_category
        raw_task_type = data.get("task_type") or data.get("item_type") or ""
        normalized_task_type = normalize_task_type(raw_task_type, resolved_category)

        item_type = normalize_task_type(
            data.get("item_type") or data.get("task_type", ""),
            resolved_category,
        )

        return Task.objects.create(
            subgoal=subgoal,
            title=data.get("title", f"Task {index}"),
            description=description,
            task_type=normalized_task_type,
            item_type=item_type,
            frequency=data.get("frequency") or None,
            difficulty_level=data.get("difficulty_level") or None,
            session_type=data.get("session_type") or None,
            trigger_after_days=data.get("trigger_after_days"),
            is_prerequisite=data.get("is_prerequisite", False),
            sequence_position=data.get("sequence_position", index - 1),
            rationale=self._to_text(data.get("rationale", "")),
            priority=data.get("priority", "medium"),
            display_order=index - 1,
            estimated_duration_minutes=data.get(
                "duration_minutes",
                data.get("estimated_duration_minutes", 60),
            ),
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
            normalized_category = normalize_goal_category_for_query(c)
            if normalized_category is None:
                goals = goals.none()
            else:
                goals = goals.filter(primary_category=normalized_category)
        if p := request.query_params.get("priority"):
            goals = goals.filter(priority=p)

        # Sort by priority (high→medium→low) then target_date
        goals = sorted(goals, key=lambda g: (PRIORITY_ORDER.get(g.priority, 9), g.target_date or timezone.localdate()))

        # --- Life Area summary (drives the 4 category cards in your UI) ------
        categories = list(GOAL_CATEGORIES)
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
            full_name = goal.user.get_full_name() if hasattr(goal.user, "get_full_name") else ""
            display_username = full_name or getattr(goal.user, "email", "") or getattr(goal.user, "username", "")
            why_summary = ""
            if isinstance(goal.why_it_matters, list) and goal.why_it_matters:
                first_reason = goal.why_it_matters[0]
                why_summary = first_reason if isinstance(first_reason, str) else ""

            goals_data.append({
                "id":                  str(goal.id),
                "title":               goal.title,
                "description":         goal.description,
                "why_it_matters":      goal.why_it_matters,
                "why_summary":         why_summary,
                "primary_category":    goal.primary_category,
                "category_pillar":     canonical_to_pillar(goal.primary_category),
                "display_username":    display_username,
                "priority":            goal.priority,
                "status":              goal.status,
                "progress_percentage": goal.progress_percentage,
                "start_date":          goal.start_date.isoformat() if goal.start_date else None,
                "target_date":         goal.target_date.isoformat() if goal.target_date else None,
                "days_remaining":      days_left,
                "is_overdue":          is_overdue,
                "is_ai_generated":     goal.is_ai_generated,
                "financial_target_amount": float(goal.financial_target_amount) if goal.financial_target_amount is not None else None,
                "financial_current_saved": float(goal.financial_current_saved) if goal.financial_current_saved is not None else None,
                "financial_goal_type": goal.financial_goal_type,
                "financial_timeline_flexibility": goal.financial_timeline_flexibility,
                "financial_feasibility_status": goal.financial_feasibility_status,
                "financial_required_monthly_savings": float(goal.financial_required_monthly_savings) if goal.financial_required_monthly_savings is not None else None,
                "financial_months_remaining": goal.financial_months_remaining,
                "financial_gap_amount": float(goal.financial_gap_amount) if goal.financial_gap_amount is not None else None,
                "illustration_url":    goal.illustration_url,
                "illustration_status": goal.illustration_status,
                # Counts for the milestone progress indicator on each card
                "milestone_count":     goal.milestone_count,
                "completed_milestones": goal.completed_milestones,
                # Attributes — only the relevant category field, not all four
                "attributes":          self._get_attributes(goal),
            })

        profile_review_state = _get_profile_review_state(request.user)
        return Response(
            {
                "life_areas": life_areas,
                "count": len(goals_data),
                "goals": goals_data,
                **profile_review_state,
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
            bucket = get_goal_attribute_bucket(goal.primary_category)
            data = getattr(attr, bucket)
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
        return Response(
            {"goal": serializer.data, **_get_profile_review_state(request.user)},
            status=status.HTTP_200_OK,
        )

    def put(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal, data=request.data)
        if serializer.is_valid():
            feasibility_metadata, feasibility_error = evaluate_financial_goal_feasibility(
                user=request.user,
                validated_data=serializer.validated_data,
                instance=goal,
            )
            if feasibility_error:
                return Response(feasibility_error, status=status.HTTP_400_BAD_REQUEST)
            if feasibility_metadata:
                serializer.validated_data.update(feasibility_metadata)

            updated_goal = serializer.save()
            evaluate_profile_review_for_goal(goal=updated_goal)
            return Response(
                {**serializer.data, **_get_profile_review_state(request.user)},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = GoalSerializer(goal, data=request.data, partial=True)
        if serializer.is_valid():
            feasibility_metadata, feasibility_error = evaluate_financial_goal_feasibility(
                user=request.user,
                validated_data=serializer.validated_data,
                instance=goal,
            )
            if feasibility_error:
                return Response(feasibility_error, status=status.HTTP_400_BAD_REQUEST)
            if feasibility_metadata:
                serializer.validated_data.update(feasibility_metadata)

            updated_goal = serializer.save()
            evaluate_profile_review_for_goal(goal=updated_goal)
            return Response(
                {**serializer.data, **_get_profile_review_state(request.user)},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, goal_id):
        goal = self._get_goal(goal_id, request.user)
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        goal.delete()  # CASCADE deletes Milestones -> SubGoals -> Tasks automatically
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalCommitmentContractDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        goal = Goal.objects.filter(id=goal_id, user=request.user).first()
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        record = GoalCommitmentRecord.objects.filter(goal=goal, user=request.user).first()
        if not record:
            # Backward-compatible read path for goals created before commitment
            # record persistence existed. This is read-only and deterministic.
            signed_name = (
                request.user.get_full_name().strip()
                if hasattr(request.user, "get_full_name")
                else ""
            ) or request.user.email
            signed_at = goal.created_at or timezone.now()
            snapshot = GoalContractTemplateService().render_snapshot(
                goal_data=goal,
                user=request.user,
                signed_name=signed_name,
                signed_at=signed_at,
                accepted_gie_commitments=[],
            )
            return Response(
                {
                    "goal_id": str(goal.id),
                    "accepted_at": signed_at,
                    "signed_name": signed_name,
                    "signed_at": signed_at,
                    "contract_snapshot": snapshot,
                    "created_at": signed_at,
                    "updated_at": goal.updated_at or signed_at,
                },
                status=status.HTTP_200_OK,
            )

        serializer = GoalCommitmentRecordReadSerializer(record)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GoalTimelineInsightAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def post(self, request, goal_id):
        goal = Goal.objects.filter(id=goal_id, user=request.user).first()
        if not goal:
            return Response({"error": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = dict(request.data or {})
        payload.setdefault("goal_id", str(goal_id))
        if str(payload.get("goal_id")) != str(goal_id):
            return Response(
                {
                    "error": "validation_error",
                    "details": {"goal_id": ["Payload goal_id must match URL goal_id."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            assert_read_only_timeline_insight_request(payload)
        except TimelineInsightBoundaryError as exc:
            return Response(
                {
                    "error": "validation_error",
                    "details": {"timeline_insight": [str(exc)]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = GoalTimelineInsightService()
        insight_payload = service.get_or_create_cached_insight(user=request.user, goal=goal)
        return Response(insight_payload, status=status.HTTP_200_OK)


class TimelineOverviewInsightAPIView(GoalProductionApiView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = TimelineOverviewInsightService()
        insight_payload = service.analyze(user=request.user)
        return Response(insight_payload, status=status.HTTP_200_OK)


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


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def illustration_endpoint(request, goal_id):
    goal = get_object_or_404(Goal, id=goal_id, user=request.user)

    if request.method == "DELETE":
        clear_goal_illustration(goal)
        payload = _build_illustration_response(goal)
        payload["message"] = "Illustration removed."
        return Response(payload, status=status.HTTP_200_OK)

    uploaded_file = request.FILES.get("image")

    if uploaded_file is None:
        return Response({"image": ["Please upload an image file."]}, status=status.HTTP_400_BAD_REQUEST)

    if uploaded_file.content_type not in ALLOWED_ILLUSTRATION_CONTENT_TYPES:
        return Response({"image": ["Please upload a JPG, PNG, or WebP image."]}, status=status.HTTP_400_BAD_REQUEST)

    if uploaded_file.size > MAX_ILLUSTRATION_SIZE_BYTES:
        return Response({"image": ["Please upload an image smaller than 5 MB."]}, status=status.HTTP_400_BAD_REQUEST)

    illustration_url = save_goal_illustration(goal, uploaded_file)
    goal.illustration_url = _build_public_illustration_url_for_request(request, illustration_url)

    payload = _build_illustration_response(goal)
    payload["message"] = "Illustration uploaded."
    return Response(payload, status=status.HTTP_200_OK)


    






