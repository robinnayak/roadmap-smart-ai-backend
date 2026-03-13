import logging
from decimal import Decimal
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from rest_framework import serializers

from .models import (
    UserCurrentSituationGoal,
    Goal,
    CommitmentContract,
    GoalAttributes,
    Milestone,
    SubGoal,
    Task,
    UserFinancialProfile,
    GoalLink,
    FinancialProgressEntry,
)
from .services.create_contract import (
    list_missing_required_goal_fields,
    normalize_why_it_matters,
    required_goal_fields_error_details,
)

logger = logging.getLogger(__name__)


class UserCurrentSituationGoalSerializer(serializers.ModelSerializer):
    # read_only=True means this won't be writable even if someone POSTs to it
    user_personal_details = None  # Replace with: UserPersonalDetailsSerializer(read_only=True, allow_null=True)

    class Meta:
        model = UserCurrentSituationGoal
        fields = [
            "id",
            "current_role",
            "age",
            "key_skills",
            "main_goals",
            "time_availability",
            "constraints",
            "priority_areas",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "ai_processing_job",
            "user_personal_details",
            "age",
        ]

    def validate_current_situation(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError(
                "current_situation must be a JSON object."
            )
        return value

    def validate_key_skills(self, value):
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("key_skills must be a list.")
        return value

    def validate_main_goals(self, value):
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("main_goals must be a list.")
        return value

    def validate_constraints(self, value):
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("constraints must be a list.")
        return value

    def validate_priority_areas(self, value):
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("priority_areas must be a list.")
        return value

    def validate_current_role(self, value):
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "current_role cannot exceed 255 characters."
            )
        return value

    def validate_time_availability(self, value):
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "time_availability cannot exceed 255 characters."
            )
        return value

    def validate_age(self, value):
        if value is not None and not (0 <= value <= 120):
            raise serializers.ValidationError("Age must be between 0 and 120.")
        return value

#---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TaskSerializer(serializers.ModelSerializer):
    """Full Task serializer — used inside SubGoal detail views."""

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "task_type",
            "priority",
            "status",
            "scheduled_date",
            "scheduled_time",
            "preferred_time_slot",
            "estimated_duration_minutes",
            "actual_duration_minutes",
            "completed_at",
            "completion_notes",
            "difficulty_rating",
            "display_order",
            "is_ai_generated",
            "ai_reasoning",
            "is_user_modified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "completed_at", "created_at", "updated_at"]

    def validate_scheduled_date(self, value):
        """Warn (but don't block) if scheduling a task in the past."""
        if value and value < timezone.localdate():
            raise serializers.ValidationError("Cannot schedule a task in the past.")
        return value

    def update(self, instance, validated_data):
        """
        Keep hierarchy progress in sync when task status changes via API edits.
        """
        requested_status = validated_data.pop("status", None)
        updated = super().update(instance, validated_data)

        if requested_status == "completed":
            if updated.status != "completed":
                updated.mark_completed(
                    notes=updated.completion_notes or "",
                    difficulty=updated.difficulty_rating,
                    actual_minutes=updated.actual_duration_minutes,
                )
            else:
                updated.subgoal.update_progress()
            return updated

        if requested_status in {"pending", "in_progress", "skipped"}:
            updated.status = requested_status
            fields_to_update = ["status", "updated_at"]
            if updated.completed_at is not None:
                updated.completed_at = None
                fields_to_update.append("completed_at")
            updated.save(update_fields=fields_to_update)

        updated.subgoal.update_progress()
        return updated


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight Task serializer for list and Dashboard views."""

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "status",
            "priority",
            "task_type",
            "scheduled_date",
            "scheduled_time",
            "preferred_time_slot",
            "estimated_duration_minutes",
            "display_order",
        ]


# ---------------------------------------------------------------------------
# SubGoal
# ---------------------------------------------------------------------------

class SubGoalSerializer(serializers.ModelSerializer):
    """
    Full SubGoal serializer with nested tasks.
    Use prefetch_related('tasks') in the view to avoid N+1 queries.
    """

    tasks = TaskSerializer(many=True, read_only=True)
    week_number = serializers.IntegerField(read_only=True)  # @property on model
    task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()

    class Meta:
        model = SubGoal
        fields = [
            "id",
            "title",
            "description",
            "priority",
            "status",
            "progress_percentage",
            "week_number",
            "start_date",
            "target_date",
            "completed_date",
            "display_order",
            "is_ai_generated",
            "ai_reasoning",
            "is_user_modified",
            "task_count",
            "completed_task_count",
            "tasks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "progress_percentage",
            "completed_date",
            "week_number",
            "created_at",
            "updated_at",
        ]

    def get_task_count(self, obj) -> int:
        return obj.tasks.count()

    def get_completed_task_count(self, obj) -> int:
        return obj.tasks.filter(status="completed").count()


class SubGoalListSerializer(serializers.ModelSerializer):
    """Lightweight SubGoal serializer — no nested tasks."""

    week_number = serializers.IntegerField(read_only=True)
    task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()

    class Meta:
        model = SubGoal
        fields = [
            "id",
            "title",
            "status",
            "progress_percentage",
            "week_number",
            "start_date",
            "target_date",
            "display_order",
            "task_count",
            "completed_task_count",
        ]

    def get_task_count(self, obj) -> int:
        return obj.tasks.count()

    def get_completed_task_count(self, obj) -> int:
        return obj.tasks.filter(status="completed").count()


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------

class MilestoneSerializer(serializers.ModelSerializer):
    """
    Full Milestone serializer with nested subgoals + tasks.
    Use prefetch_related('subgoals__tasks') in the view.
    """

    subgoals = SubGoalSerializer(many=True, read_only=True)
    subgoal_count = serializers.SerializerMethodField()
    completed_subgoal_count = serializers.SerializerMethodField()
    total_task_count = serializers.SerializerMethodField()

    class Meta:
        model = Milestone
        fields = [
            "id",
            "title",
            "description",
            "success_criteria",
            "priority",
            "status",
            "progress_percentage",
            "start_date",
            "target_date",
            "completed_date",
            "display_order",
            "is_ai_generated",
            "ai_reasoning",
            "is_user_modified",
            "subgoal_count",
            "completed_subgoal_count",
            "total_task_count",
            "subgoals",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "progress_percentage",
            "completed_date",
            "created_at",
            "updated_at",
        ]

    def get_subgoal_count(self, obj) -> int:
        return obj.subgoals.count()

    def get_completed_subgoal_count(self, obj) -> int:
        return obj.subgoals.filter(status="completed").count()

    def get_total_task_count(self, obj) -> int:
        # Relies on prefetch_related('subgoals__tasks') being set in the view
        return sum(sg.tasks.count() for sg in obj.subgoals.all())


class MilestoneListSerializer(serializers.ModelSerializer):
    """Lightweight Milestone serializer for Timeline / Goals page list."""

    subgoal_count = serializers.SerializerMethodField()
    completed_subgoal_count = serializers.SerializerMethodField()

    class Meta:
        model = Milestone
        fields = [
            "id",
            "title",
            "status",
            "progress_percentage",
            "start_date",
            "target_date",
            "display_order",
            "subgoal_count",
            "completed_subgoal_count",
        ]

    def get_subgoal_count(self, obj) -> int:
        return obj.subgoals.count()

    def get_completed_subgoal_count(self, obj) -> int:
        return obj.subgoals.filter(status="completed").count()


# ---------------------------------------------------------------------------
# GoalAttributes
# ---------------------------------------------------------------------------

class GoalAttributesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoalAttributes
        fields = ["id", "financial_data", "career_data", "health_data", "personal_data",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


# ---------------------------------------------------------------------------
# Goal — main serializer (handles create + update)
# ---------------------------------------------------------------------------

class GoalSerializer(serializers.ModelSerializer):
    """
    Full Goal serializer.

    - goal_attributes_input: optional natural-language string; if provided,
      the AI extractor runs and creates/updates GoalAttributes automatically.
    - attributes: included read-only so the client always gets back the full
      picture in a single response.
    - days_remaining / is_overdue: read-only @property values from the model.
    """

    days_remaining = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()
    attributes = GoalAttributesSerializer(read_only=True)

    # Write-only: triggers AI attribute extraction on create
    goal_attributes_input = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Natural language description used to auto-extract GoalAttributes.",
    )
    commitment_confirmed = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text="Must be true when creating a goal.",
    )
    commitment_note = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Optional motivational commitment line captured at creation time.",
    )
    why_do_i_want_this = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Optional dedicated purpose statement for the goal.",
    )
    specific_measurable_target = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Optional explicit measurable target for the goal.",
    )
    financial_proceed_anyway = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )

    class Meta:
        model = Goal
        fields = [
            "id",
            "title",
            "description",
            "why_it_matters",
            "primary_category",
            "impact_dimensions",
            "priority",
            "status",
            "progress_percentage",
            "start_date",
            "target_date",
            "days_remaining",
            "is_overdue",
            "is_ai_generated",
            "ai_feasibility_score",
            "ai_reasoning",
            "is_user_modified",
            "attributes",
            "goal_attributes_input",
            "commitment_confirmed",
            "commitment_note",
            "why_do_i_want_this",
            "specific_measurable_target",
            "financial_target_amount",
            "financial_current_saved",
            "financial_goal_type",
            "financial_timeline_flexibility",
            "financial_feasibility_status",
            "financial_required_monthly_savings",
            "financial_months_remaining",
            "financial_gap_amount",
            "financial_proceed_anyway",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "progress_percentage",
            "is_user_modified",
            "days_remaining",
            "is_overdue",
            "attributes",
            "created_at",
            "updated_at",
        ]

    # --- Validation ---

    def validate_impact_dimensions(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        return value

    def validate_target_date(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("Target date cannot be in the past.")
        return value

    def validate_why_it_matters(self, value):
        normalized = normalize_why_it_matters(value)
        return normalized

    def validate(self, attrs):
        start = attrs.get("start_date") or (self.instance.start_date if self.instance else None)
        target = attrs.get("target_date") or (self.instance.target_date if self.instance else None)
        if start and target and target <= start:
            raise serializers.ValidationError(
                {"target_date": "Target date must be after start date."}
            )

        if self.instance is None:
            missing_fields = list_missing_required_goal_fields(attrs)
            if missing_fields:
                raise serializers.ValidationError(
                    required_goal_fields_error_details(missing_fields)
                )

        primary_category = attrs.get("primary_category") or (
            self.instance.primary_category if self.instance else None
        )
        if primary_category == "financial":
            request = self.context.get("request")
            if self.instance is None and request is not None:
                if not UserFinancialProfile.objects.filter(user=request.user).exists():
                    raise serializers.ValidationError(
                        {"financial_profile": "Complete your financial profile before creating a financial goal."}
                    )

            target_amount = attrs.get("financial_target_amount", getattr(self.instance, "financial_target_amount", None))
            current_saved = attrs.get("financial_current_saved", getattr(self.instance, "financial_current_saved", None))
            timeline = attrs.get(
                "financial_timeline_flexibility",
                getattr(self.instance, "financial_timeline_flexibility", None),
            )
            goal_type = attrs.get("financial_goal_type", getattr(self.instance, "financial_goal_type", None))
            target_date = attrs.get("target_date") or (self.instance.target_date if self.instance else None)

            missing_fields = {}
            if target_amount is None:
                missing_fields["financial_target_amount"] = "This field is required for financial goals."
            if current_saved is None:
                missing_fields["financial_current_saved"] = "This field is required for financial goals."
            if timeline in (None, ""):
                missing_fields["financial_timeline_flexibility"] = "This field is required for financial goals."
            if goal_type in (None, ""):
                missing_fields["financial_goal_type"] = "This field is required for financial goals."
            if not target_date:
                missing_fields["target_date"] = "Target date is required for financial goals."
            if missing_fields:
                raise serializers.ValidationError(missing_fields)

            if target_amount is not None and target_amount <= 0:
                raise serializers.ValidationError({"financial_target_amount": "Target amount must be greater than 0."})
            if current_saved is not None and current_saved < 0:
                raise serializers.ValidationError({"financial_current_saved": "Current saved amount cannot be negative."})
            if target_amount is not None and current_saved is not None and current_saved > target_amount:
                raise serializers.ValidationError(
                    {"financial_current_saved": "Current saved cannot exceed target amount."}
                )
        return attrs

    # --- Attribute extraction helper ---

    def _extract_and_save_attributes(self, goal: Goal, user_input: str, user) -> bool:
        """
        Calls the AI extractor and creates or updates GoalAttributes.
        Returns True on success, False on failure (non-fatal).
        """
        try:
            from ai.services.text_extraction import GoalAttributeExtractor

            result = GoalAttributeExtractor().extract_goal_attributes(
                user_input=user_input,
                user=user,
                goal_id=str(goal.id),
            )

            if result.get("status") != "success" or "data" not in result:
                logger.warning("Attribute extraction returned no data for goal %s", goal.id)
                return False

            extracted = result["data"]
            category = goal.primary_category.lower()
            
            category_field_map = {
                "financial": "financial_data",
                "career":    "career_data",
                "health":    "health_data",
                "personal":  "personal_data",
            }

            defaults = {f: None for f in category_field_map.values()}
            if category in category_field_map:
                defaults[category_field_map[category]] = extracted

            GoalAttributes.objects.update_or_create(goal=goal, defaults=defaults)
            logger.info("GoalAttributes saved for goal %s", goal.id)
            return True

        except ImproperlyConfigured:
            from ai.config import build_ai_runtime_error_message

            logger.warning(
                "Skipping goal attribute extraction for goal %s: %s",
                goal.id,
                build_ai_runtime_error_message(),
            )
            return False
        except Exception:
            logger.exception("Failed to extract attributes for goal %s", goal.id)
            return False

    # --- Create / Update ---

    def create(self, validated_data):
        goal_attributes_input = validated_data.pop("goal_attributes_input", None)
        validated_data.pop("commitment_confirmed", None)
        validated_data.pop("commitment_note", None)
        why_do_i_want_this = validated_data.pop("why_do_i_want_this", "").strip()
        specific_measurable_target = validated_data.pop(
            "specific_measurable_target", ""
        ).strip()
        validated_data.pop("financial_proceed_anyway", None)

        if why_do_i_want_this or specific_measurable_target:
            impact_dimensions = dict(validated_data.get("impact_dimensions") or {})
            if why_do_i_want_this:
                impact_dimensions["why_do_i_want_this"] = why_do_i_want_this
            if specific_measurable_target:
                impact_dimensions["specific_measurable_target"] = specific_measurable_target
            validated_data["impact_dimensions"] = impact_dimensions

        # User-created goals are always marked as modified
        if not validated_data.get("is_ai_generated", False):
            validated_data["is_user_modified"] = True

        goal = Goal.objects.create(**validated_data)

        if goal_attributes_input:
            user = self.context["request"].user
            self._extract_and_save_attributes(goal, goal_attributes_input, user)

        return goal

    def update(self, instance, validated_data):
        # Attribute extraction only happens at create time
        validated_data.pop("goal_attributes_input", None)
        validated_data.pop("financial_proceed_anyway", None)
        why_do_i_want_this = validated_data.pop("why_do_i_want_this", "").strip()
        specific_measurable_target = validated_data.pop(
            "specific_measurable_target", ""
        ).strip()

        if why_do_i_want_this or specific_measurable_target:
            impact_dimensions = dict(instance.impact_dimensions or {})
            if why_do_i_want_this:
                impact_dimensions["why_do_i_want_this"] = why_do_i_want_this
            if specific_measurable_target:
                impact_dimensions["specific_measurable_target"] = specific_measurable_target
            validated_data["impact_dimensions"] = impact_dimensions

        # If a user edits an AI-generated goal, flag it
        if instance.is_ai_generated:
            validated_data["is_user_modified"] = True

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# Goal — list & detail variants (read-only, with hierarchy counts)
# ---------------------------------------------------------------------------

class GoalListSerializer(serializers.ModelSerializer):
    """
    Lightweight Goal serializer for the Goals page list.
    Use prefetch_related('milestones') in the view.
    """

    days_remaining = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()
    milestone_count = serializers.SerializerMethodField()
    completed_milestones = serializers.SerializerMethodField()
    needs_profile_review = serializers.SerializerMethodField()

    class Meta:
        model = Goal
        fields = [
            "id",
            "title",
            "primary_category",
            "priority",
            "status",
            "progress_percentage",
            "start_date",
            "target_date",
            "days_remaining",
            "is_overdue",
            "is_ai_generated",
            "milestone_count",
            "completed_milestones",
            "needs_profile_review",
        ]

    def get_milestone_count(self, obj) -> int:
        return obj.milestones.count()

    def get_completed_milestones(self, obj) -> int:
        return obj.milestones.filter(status="completed").count()

    def get_needs_profile_review(self, obj) -> bool:
        profile = UserFinancialProfile.objects.filter(user=obj.user).first()
        return bool(profile and profile.needs_review)


class GoalDetailSerializer(serializers.ModelSerializer):
    """
    Full Goal detail with complete hierarchy.
    View should use:
      prefetch_related('milestones__subgoals__tasks', 'attributes')
    """

    attributes = GoalAttributesSerializer(read_only=True)
    milestones = MilestoneSerializer(many=True, read_only=True)
    days_remaining = serializers.ReadOnlyField()
    is_overdue = serializers.ReadOnlyField()

    # Aggregate counts — resolved from prefetched data, no extra queries
    milestone_count = serializers.SerializerMethodField()
    completed_milestone_count = serializers.SerializerMethodField()
    total_subgoal_count = serializers.SerializerMethodField()
    total_task_count = serializers.SerializerMethodField()
    completed_task_count = serializers.SerializerMethodField()

    class Meta:
        model = Goal
        fields = [
            "id",
            "title",
            "description",
            "why_it_matters",
            "primary_category",
            "impact_dimensions",
            "priority",
            "status",
            "progress_percentage",
            "start_date",
            "target_date",
            "days_remaining",
            "is_overdue",
            "is_ai_generated",
            "ai_feasibility_score",
            "ai_reasoning",
            "is_user_modified",
            "milestone_count",
            "completed_milestone_count",
            "total_subgoal_count",
            "total_task_count",
            "completed_task_count",
            "attributes",
            "milestones",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields  # detail serializer is read-only

    def get_milestone_count(self, obj) -> int:
        return obj.milestones.count()

    def get_completed_milestone_count(self, obj) -> int:
        return obj.milestones.filter(status="completed").count()

    def get_total_subgoal_count(self, obj) -> int:
        return sum(m.subgoals.count() for m in obj.milestones.all())

    def get_total_task_count(self, obj) -> int:
        return sum(
            sg.tasks.count()
            for m in obj.milestones.all()
            for sg in m.subgoals.all()
        )

    def get_completed_task_count(self, obj) -> int:
        return sum(
            sg.tasks.filter(status="completed").count()
            for m in obj.milestones.all()
            for sg in m.subgoals.all()
        )


class CommitmentContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommitmentContract
        fields = [
            "id",
            "identity_statement",
            "signature_name",
            "cc_email",
            "goals_snapshot",
            "deadlines_snapshot",
            "is_signed",
            "signed_at",
            "pdf_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "goals_snapshot",
            "deadlines_snapshot",
            "is_signed",
            "signed_at",
            "pdf_url",
            "created_at",
            "updated_at",
        ]


class CommitmentContractSignSerializer(serializers.Serializer):
    identity_statement = serializers.CharField(max_length=2000)
    signature_name = serializers.CharField(max_length=255)
    cc_email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)


class UserFinancialProfileSerializer(serializers.ModelSerializer):
    situation_changed = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )

    class Meta:
        model = UserFinancialProfile
        fields = [
            "id",
            "employment_type",
            "monthly_income_range",
            "monthly_surplus_range",
            "primary_skill_area",
            "total_current_savings_range",
            "needs_review",
            "review_reason",
            "last_updated",
            "created_at",
            "updated_at",
            "situation_changed",
        ]
        read_only_fields = [
            "id",
            "needs_review",
            "review_reason",
            "last_updated",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        validated_data.pop("situation_changed", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("situation_changed", None)
        return super().update(instance, validated_data)


class FinancialFeasibilitySerializer(serializers.Serializer):
    target_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    current_saved = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0"),
    )
    target_date = serializers.DateField()
    timeline_flexibility = serializers.ChoiceField(
        choices=["fixed", "somewhat_flexible", "very_flexible"]
    )

    def validate(self, attrs):
        if attrs["current_saved"] > attrs["target_amount"]:
            raise serializers.ValidationError({"current_saved": "Cannot exceed target_amount."})
        return attrs


class GoalLinkSerializer(serializers.ModelSerializer):
    contributing_goal_title = serializers.CharField(source="contributing_goal.title", read_only=True)
    contributing_goal_status = serializers.CharField(source="contributing_goal.status", read_only=True)
    contributing_goal_category = serializers.CharField(source="contributing_goal.primary_category", read_only=True)

    class Meta:
        model = GoalLink
        fields = [
            "id",
            "source_goal",
            "contributing_goal",
            "contributing_goal_title",
            "contributing_goal_status",
            "contributing_goal_category",
            "link_type",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "source_goal"]

    def validate(self, attrs):
        source_goal = self.context["source_goal"]
        contributing_goal = attrs["contributing_goal"]
        if source_goal.primary_category != "financial":
            raise serializers.ValidationError("Source goal must be financial.")
        if contributing_goal.primary_category not in {"career", "personal"}:
            raise serializers.ValidationError("Contributing goal must be career or personal.")
        if contributing_goal.user_id != source_goal.user_id:
            raise serializers.ValidationError("Contributing goal must belong to the same user.")
        return attrs


class FinancialProgressEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialProgressEntry
        fields = [
            "id",
            "goal",
            "user",
            "month",
            "planned_savings",
            "actual_savings",
            "running_total_saved",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "goal", "user", "running_total_saved", "created_at", "updated_at"]

    def validate_month(self, value):
        if value.day != 1:
            raise serializers.ValidationError("Month must be the first day of the month (YYYY-MM-01).")
        return value

    def validate(self, attrs):
        planned = attrs.get("planned_savings")
        actual = attrs.get("actual_savings")
        if planned is not None and planned < 0:
            raise serializers.ValidationError({"planned_savings": "Cannot be negative."})
        if actual is not None and actual < 0:
            raise serializers.ValidationError({"actual_savings": "Cannot be negative."})
        return attrs
