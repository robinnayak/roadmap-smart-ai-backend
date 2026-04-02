from rest_framework import serializers

from gie.models import GIEAdaptationProposal, GIEPlanSnapshot, GIESession, GIESlotDefinition, GIESlotState, GIETurn
from goal.services.create_contract import COMMITMENT_REQUIRED_FIELDS, list_missing_commitment_fields, required_goal_fields_error_details
from goal.services.category_pillars import normalize_category_pillar


class GIEGoalStartRequestSerializer(serializers.Serializer):
    goal_text = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)


class GIESessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GIESession
        fields = [
            "id",
            "goal_text",
            "goal_domain",
            "status",
            "phase",
            "current_question",
            "total_questions",
            "current_question_number",
            "required_slot_count",
            "filled_required_slot_count",
            "completeness_percent",
            "created_at",
            "updated_at",
            "finalized_at",
        ]
        read_only_fields = [
            "id",
            "goal_text",
            "goal_domain",
            "status",
            "phase",
            "current_question",
            "total_questions",
            "current_question_number",
            "required_slot_count",
            "filled_required_slot_count",
            "completeness_percent",
            "created_at",
            "updated_at",
            "finalized_at",
        ]


class GIESlotDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GIESlotDefinition
        fields = [
            "key",
            "label",
            "description",
            "required",
            "data_type",
            "enum_values",
            "validation",
        ]


class GIESlotStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GIESlotState
        fields = [
            "slot_key",
            "required",
            "status",
            "value",
            "source",
            "confidence",
            "last_updated_turn_index",
            "missing_reason",
        ]


class GIETurnSubmitRequestSerializer(serializers.Serializer):
    client_turn_id = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True, max_length=100)
    answer = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)


class GIETurnSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(source="session.id", read_only=True)

    class Meta:
        model = GIETurn
        fields = [
            "id",
            "session_id",
            "turn_index",
            "role",
            "kind",
            "content",
            "client_turn_id",
            "applied",
            "created_at",
        ]


class GIESchemaResponseSerializer(serializers.Serializer):
    required_slots = GIESlotDefinitionSerializer(many=True)
    optional_slots = GIESlotDefinitionSerializer(many=True)


class GIEGoalStartResponseSerializer(serializers.Serializer):
    session = GIESessionSerializer()
    schema = GIESchemaResponseSerializer()
    slot_state = GIESlotStateSerializer(many=True)
    next_prompt = serializers.JSONField(allow_null=True, required=False)
    category = serializers.CharField(allow_null=True, required=False)
    category_label = serializers.CharField(allow_null=True, required=False)
    total_questions = serializers.IntegerField(allow_null=True, required=False)
    current_question_number = serializers.IntegerField(allow_null=True, required=False)
    gie_question = serializers.CharField(allow_null=True, required=False)
    gie_suggestions = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        required=False,
    )


class GIETurnSubmitResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    turn = GIETurnSerializer()
    slot_updates = GIESlotStateSerializer(many=True)
    completeness = serializers.JSONField()
    next_prompt = serializers.JSONField(allow_null=True, required=False)
    session_status = serializers.CharField()
    current_question_number = serializers.IntegerField(allow_null=True, required=False)
    is_llm_complete = serializers.BooleanField(allow_null=True, required=False)
    gie_question = serializers.CharField(allow_null=True, required=False)
    gie_suggestions = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        required=False,
    )


class GIEFinalizeCommitmentDecisionSerializer(serializers.Serializer):
    id = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)
    decision = serializers.ChoiceField(choices=["accepted", "pending", "revised", "rejected"])
    revision_note = serializers.CharField(required=False, allow_null=True, allow_blank=True, trim_whitespace=True)


class GIEHabitConfirmationSerializer(serializers.Serializer):
    habit_name = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True, max_length=255)
    decision = serializers.ChoiceField(choices=["accepted", "rejected"])


class GIEFinalizeRequestSerializer(serializers.Serializer):
    commitments = GIEFinalizeCommitmentDecisionSerializer(many=True, required=False, default=list)
    habit_confirmations = GIEHabitConfirmationSerializer(many=True, required=False, default=list)
    goal_context = serializers.JSONField(required=False)

    def validate_goal_context(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("goal_context must be a JSON object.")
        if "category_pillar" in value:
            raw_pillar = value.get("category_pillar")
            if raw_pillar in ("", None):
                value["category_pillar"] = None
            else:
                normalized_pillar = normalize_category_pillar(raw_pillar)
                if normalized_pillar is None:
                    raise serializers.ValidationError(
                        {"category_pillar": "Use one of: Money, Health, Career, Learning, Relationships, Personal."}
                    )
                value["category_pillar"] = normalized_pillar
        missing_commitment_fields = [
            field
            for field in list_missing_commitment_fields(value)
            if field != "contract_snapshot"
        ]
        for field in COMMITMENT_REQUIRED_FIELDS:
            if field == "contract_snapshot":
                continue
            if field not in value and field not in missing_commitment_fields:
                missing_commitment_fields.append(field)
        if missing_commitment_fields:
            raise serializers.ValidationError(required_goal_fields_error_details(missing_commitment_fields))
        return value


class GIEAutofillRequestSerializer(serializers.Serializer):
    goal_context = serializers.JSONField(required=False)
    refine_language = serializers.BooleanField(required=False, default=False)

    def validate_goal_context(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("goal_context must be a JSON object.")
        if "category_pillar" in value:
            raw_pillar = value.get("category_pillar")
            if raw_pillar in ("", None):
                value["category_pillar"] = None
            else:
                normalized_pillar = normalize_category_pillar(raw_pillar)
                if normalized_pillar is None:
                    raise serializers.ValidationError(
                        {"category_pillar": "Use one of: Money, Health, Career, Learning, Relationships, Personal."}
                    )
                value["category_pillar"] = normalized_pillar
        return value


class GIERIESignalConfirmedHabitSerializer(serializers.Serializer):
    habit_name = serializers.CharField()
    rationale = serializers.CharField()
    suggested_order = serializers.IntegerField(min_value=1)


class GIERIESignalSerializer(serializers.Serializer):
    goal_priority = serializers.ChoiceField(choices=["low", "medium", "high"])
    confirmed_habits = GIERIESignalConfirmedHabitSerializer(many=True)
    suggested_sequence_order = serializers.ListField(child=serializers.CharField())
    estimated_daily_capacity_minutes = serializers.IntegerField(min_value=0)


class GIEPlanSnapshotSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(source="session.id", read_only=True)
    rie_signal = GIERIESignalSerializer(read_only=True)

    class Meta:
        model = GIEPlanSnapshot
        fields = [
            "id",
            "session_id",
            "status",
            "goal_summary",
            "assumptions",
            "risks",
            "milestones",
            "weekly_routine_guidance",
            "rie_signal",
            "created_at",
        ]


class GIEAdaptationSignalSerializer(serializers.Serializer):
    signal_type = serializers.ChoiceField(choices=["routine", "journal", "progress", "manual"])
    trigger = serializers.ChoiceField(
        choices=[
            "missed_tasks_streak",
            "declining_engagement",
            "negative_sentiment",
            "stalled_progress",
            "timeline_change",
        ]
    )
    value = serializers.JSONField(required=False)
    observed_at = serializers.DateTimeField()


class GIEAdaptationRequestSerializer(serializers.Serializer):
    signals = GIEAdaptationSignalSerializer(many=True, required=True)

    def validate_signals(self, value):
        if not value:
            raise serializers.ValidationError("At least one signal is required.")
        return value


class GIEAdaptationProposalSerializer(serializers.ModelSerializer):
    proposal_id = serializers.UUIDField(source="id", read_only=True)
    session_id = serializers.UUIDField(source="session.id", read_only=True)

    class Meta:
        model = GIEAdaptationProposal
        fields = [
            "proposal_id",
            "session_id",
            "trigger",
            "action",
            "reason",
            "changes",
            "recommended_commitment_updates",
            "created_at",
        ]
