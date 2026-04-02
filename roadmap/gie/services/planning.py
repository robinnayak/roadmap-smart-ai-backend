from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from gie.models import GIEPlanSnapshot, GIESession, GIESlotState
from gie.services.habit_ranking import GIEHabitRankingService
from gie.services.language_refinement import GIEGoalLanguageRefinementService
from gie.services.timeline_feasibility import GIETimelineFeasibilityService
from gie.services.turn_pipeline import GIETurnPipelineService
from gie.services.unified_context import GIEUnifiedContextService
from goal.services.create_contract import (
    list_missing_required_goal_fields,
    normalize_why_it_matters,
    required_goal_fields_error_details,
)
from goal.services.category_resolver import (
    classify_goal_category_deterministic,
    normalize_goal_category_for_storage,
)
from goal.services.category_pillars import canonical_to_pillar, resolve_canonical_category
from goal.services.contract_template import GoalContractTemplateService
from goal.views import CreateGoalWithHierarchyAPIView


@dataclass
class GIEFinalizeBridgeResult:
    ok: bool
    status_code: int
    payload: dict


class GIEPlanningService:
    HABIT_SUGGESTIONS_SLOT_KEY = "__habit_ranked_suggestions"
    GOAL_DETAILS_AUTOFILL_SLOT_KEY = "__goal_details_autofill"
    PRIORITY_SLOT_KEYS = ("priority", "goal_priority")
    PRIORITY_DATE_SLOT_KEYS = ("timeline_target_date", "target_date")
    HIGH_URGENCY_TOKENS = (
        "urgent",
        "asap",
        "must",
        "need to",
        "deadline",
        "race",
        "interview",
        "review",
        "performance review",
        "birthday",
        "wedding",
        "exam",
    )
    HIGH_IMPORTANCE_TOKENS = (
        "very important",
        "really important",
        "top priority",
        "highest priority",
        "non-negotiable",
        "critical",
    )
    EXPLORATORY_TOKENS = (
        "maybe",
        "might",
        "thinking about",
        "considering",
        "explore",
        "someday",
    )
    EVENT_DEADLINE_TOKENS = (
        "race",
        "interview",
        "performance review",
        "birthday",
        "wedding",
        "exam",
    )
    MEASURABLE_SLOT_KEYS = (
        "savings_target",
        "weekly_training_days",
        "daily_session_minutes",
        "meal_prep_days_per_week",
        "meals_to_prepare_per_day",
        "protein_goal_grams_per_day",
        "prep_time_per_day_minutes",
        "daily_practice_minutes",
        "monthly_income",
        "monthly_fixed_expenses",
        "existing_debt",
    )
    CAPACITY_SLOT_KEYS = (
        "weekly_effort_hours",
        "weekly_study_hours",
        "weekly_execution_hours",
        "weekly_commitment_hours",
        "weekly_availability_days",
        "weekly_training_days",
        "daily_practice_minutes",
        "daily_session_minutes",
        "meal_prep_days_per_week",
        "prep_time_per_day_minutes",
    )
    CONTRACT_TEMPLATE_SERVICE = GoalContractTemplateService()

    @staticmethod
    def _build_autofill_slot_value(payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        slot_value = dict(payload)
        slot_value.pop("category_pillar", None)
        return slot_value

    @staticmethod
    def _resolve_primary_category_from_unified_context(*, session: GIESession, unified_context: dict) -> str:
        slot_profile = unified_context.get("slot_profile", {}) if isinstance(unified_context, dict) else {}
        goal_domain = str(slot_profile.get("goal_domain") or "").strip().lower()
        domain_category_map = {
            "running_endurance": "fitness",
            "nutrition": "nutrition",
            "wellness": "wellness",
            "finance": "finance",
            "skill_acquisition": "learning",
            "career": "career",
        }
        mapped = domain_category_map.get(goal_domain)
        if mapped:
            return mapped

        resolved_title = str(((unified_context or {}).get("goal_details") or {}).get("title") or session.goal_text.strip())
        resolved_description = str(((unified_context or {}).get("goal_details") or {}).get("description") or "")
        return normalize_goal_category_for_storage(
            classify_goal_category_deterministic(
                goal_title=resolved_title,
                goal_description=resolved_description,
            ),
            goal_title=resolved_title,
            goal_description=resolved_description,
        )

    @staticmethod
    def get_latest_health_profile(*, user):
        try:
            from routine.health_profile_selector import get_effective_profile
        except Exception:
            return None
        return get_effective_profile(user=user)

    @classmethod
    def _extract_ranked_habits_from_slot_states(cls, *, slot_states: list[GIESlotState]) -> list[dict]:
        state_by_key = {state.slot_key: state for state in slot_states}
        habit_suggestion_state = state_by_key.get(cls.HABIT_SUGGESTIONS_SLOT_KEY)
        if habit_suggestion_state and isinstance(habit_suggestion_state.value, list):
            return [item for item in habit_suggestion_state.value if isinstance(item, dict)]
        return []

    @classmethod
    def ensure_ranked_habit_suggestions(cls, *, session: GIESession) -> tuple[list[dict], GIESlotState]:
        slot_states = list(session.slot_states.all().order_by("slot_key"))
        ranked_habit_suggestions = cls._extract_ranked_habits_from_slot_states(slot_states=slot_states)
        if ranked_habit_suggestions:
            habit_state = session.slot_states.get(slot_key=cls.HABIT_SUGGESTIONS_SLOT_KEY)
            return ranked_habit_suggestions, habit_state

        health_profile = cls.get_latest_health_profile(user=session.user)
        ranked_habit_suggestions = GIEHabitRankingService.rank(
            session=session,
            slot_states=slot_states,
            health_profile=health_profile,
        )
        habit_state, _ = GIESlotState.objects.update_or_create(
            session=session,
            slot_key=cls.HABIT_SUGGESTIONS_SLOT_KEY,
            defaults={
                "required": False,
                "status": GIESlotState.STATUS_LOCKED,
                "value": ranked_habit_suggestions,
                "source": GIESlotState.SOURCE_INFERENCE,
                "confidence": 0.91,
                "last_updated_turn_index": None,
                "missing_reason": None,
            },
        )
        return ranked_habit_suggestions, habit_state

    @classmethod
    def ensure_goal_details_autofill_state(
        cls,
        *,
        session: GIESession,
        slot_states: list[GIESlotState] | None = None,
        form_goal_context: dict | None = None,
        refine_language: bool = False,
    ) -> GIESlotState:
        resolved_slot_states = slot_states if slot_states is not None else list(session.slot_states.all().order_by("slot_key"))
        unified_context = GIEUnifiedContextService.build(session=session, slot_states=resolved_slot_states)
        resolved_priority = cls._resolve_goal_priority(slot_states=resolved_slot_states, unified_context=unified_context)
        autofill_payload = cls.build_goal_autofill_payload(
            session=session,
            unified_context=unified_context,
            slot_states=resolved_slot_states,
            resolved_priority=resolved_priority,
            form_goal_context=form_goal_context,
            refine_language=refine_language,
        )
        autofill_state, _ = GIESlotState.objects.update_or_create(
            session=session,
            slot_key=cls.GOAL_DETAILS_AUTOFILL_SLOT_KEY,
            defaults={
                "required": False,
                "status": GIESlotState.STATUS_LOCKED,
                "value": cls._build_autofill_slot_value(autofill_payload),
                "source": GIESlotState.SOURCE_INFERENCE,
                "confidence": 0.95,
                "last_updated_turn_index": None,
                "missing_reason": None,
            },
        )
        return autofill_state

    @classmethod
    def build_goal_autofill_payload(
        cls,
        *,
        session: GIESession,
        unified_context: dict,
        slot_states: list[GIESlotState],
        resolved_priority: str,
        form_goal_context: dict | None = None,
        refine_language: bool = False,
    ) -> dict:
        goal_details = unified_context.get("goal_details", {})
        timeline_context = unified_context.get("timeline", {})
        inferred_primary_category = cls._resolve_primary_category_from_unified_context(
            session=session,
            unified_context=unified_context,
        )
        base_payload = {
            "title": str(goal_details.get("title") or session.goal_text.strip())[:255],
            "primary_category": inferred_primary_category,
            "category_pillar": None,
            "priority": resolved_priority,
            "description": str(goal_details.get("description") or ""),
            "why_do_i_want_this": str(goal_details.get("why") or ""),
            "specific_measurable_target": str(goal_details.get("measurable_target") or ""),
            "why_it_matters": normalize_why_it_matters(goal_details.get("why") or session.goal_text),
            "target_date": str(timeline_context.get("end_date") or (timezone.localdate() + timedelta(days=90)).isoformat()),
        }

        context = form_goal_context if isinstance(form_goal_context, dict) else {}

        def _string_override(key: str):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        for key in ("title", "description", "why_do_i_want_this", "specific_measurable_target", "target_date"):
            override = _string_override(key)
            if override:
                base_payload[key] = override[:255] if key == "title" else override

        priority = context.get("priority")
        if isinstance(priority, str):
            normalized_priority = priority.strip().lower()
            if normalized_priority in {"low", "medium", "high"}:
                base_payload["priority"] = normalized_priority

        reasons_override = normalize_why_it_matters(context.get("why_it_matters"))
        if reasons_override:
            base_payload["why_it_matters"] = reasons_override

        if "primary_category" in context or "category_pillar" in context:
            explicit_primary = context.get("primary_category")
            explicit_pillar = context.get("category_pillar")
            if explicit_primary in (None, "") and explicit_pillar in (None, ""):
                base_payload["primary_category"] = resolve_canonical_category(
                    base_payload.get("primary_category"),
                    None,
                    base_payload.get("title", ""),
                    base_payload.get("description", ""),
                )
            else:
                base_payload["primary_category"] = resolve_canonical_category(
                    explicit_primary,
                    explicit_pillar,
                    base_payload.get("title", ""),
                    base_payload.get("description", ""),
                )
        else:
            base_payload["primary_category"] = resolve_canonical_category(
                base_payload.get("primary_category"),
                None,
                base_payload.get("title", ""),
                base_payload.get("description", ""),
            )
        base_payload["category_pillar"] = canonical_to_pillar(base_payload["primary_category"])

        if refine_language:
            base_payload = GIEGoalLanguageRefinementService.refine_autofill_payload(
                payload=base_payload,
                raw_goal=str(unified_context.get("raw_goal") or session.goal_text),
            )
            base_payload["primary_category"] = resolve_canonical_category(
                base_payload.get("primary_category"),
                base_payload.get("category_pillar"),
                base_payload.get("title", ""),
                base_payload.get("description", ""),
            )
            base_payload["category_pillar"] = canonical_to_pillar(base_payload["primary_category"])

        return base_payload

    @staticmethod
    def build_plan_payload(*, session: GIESession, slot_states: list[GIESlotState], unified_context: dict) -> dict:
        state_by_key = {state.slot_key: state for state in slot_states}
        timeline_context = unified_context.get("timeline", {})
        goal_details = unified_context.get("goal_details", {})
        target_date = str(timeline_context.get("end_date") or (timezone.localdate() + timedelta(days=90)).isoformat())
        effort_state = (
            state_by_key.get("weekly_effort_hours")
            or state_by_key.get("weekly_commitment_hours")
            or state_by_key.get("weekly_training_days")
            or state_by_key.get("daily_practice_minutes")
            or state_by_key.get("daily_session_minutes")
        )
        effort_hint = effort_state.value if effort_state and effort_state.value else 4
        ranked_habits = GIEPlanningService._extract_ranked_habits_from_slot_states(slot_states=slot_states)
        habit_assumptions = [
            f"Habit focus: {item.get('habit_name')} - {item.get('rationale')}"
            for item in ranked_habits[:3]
            if isinstance(item, dict)
        ]

        return {
            "goal_summary": str(goal_details.get("description") or session.goal_text.strip()),
            "assumptions": [f"User can commit around {effort_hint} focused effort units per week.", *habit_assumptions],
            "risks": ["Execution consistency may fluctuate due to competing priorities."],
            "milestones": [
                {
                    "title": "Foundation setup",
                    "target_date": target_date,
                    "success_metric": "Complete first milestone checkpoint on schedule",
                }
            ],
            "weekly_routine_guidance": [
                {"weekday": "monday", "focus": "planning", "suggested_minutes": 45},
                {"weekday": "wednesday", "focus": "execution", "suggested_minutes": 45},
                {"weekday": "saturday", "focus": "review", "suggested_minutes": 30},
            ],
        }

    @staticmethod
    def materialize_commitments(*, commitments_input: list[dict], plan_payload: dict, unified_context: dict) -> list[dict]:
        default_milestone_title = (plan_payload.get("milestones") or [{}])[0].get("title", "Milestone 1")
        indexed_inputs = {item["id"]: item for item in commitments_input}
        primary_commitment, review_commitment = GIEPlanningService._build_commitment_statements_from_context(
            plan_payload=plan_payload,
            unified_context=unified_context,
        )
        base_items = [
            {
                "id": "c1",
                "title": "Execution consistency",
                "statement": primary_commitment,
                "linked_milestone_title": default_milestone_title,
                "decision": "pending",
                "revision_note": None,
            },
            {
                "id": "c2",
                "title": "Weekly review",
                "statement": review_commitment,
                "linked_milestone_title": default_milestone_title,
                "decision": "pending",
                "revision_note": None,
            },
        ]

        merged = []
        for item in base_items:
            incoming = indexed_inputs.get(item["id"])
            if incoming:
                merged.append(
                    {
                        **item,
                        "decision": incoming["decision"],
                        "revision_note": incoming.get("revision_note"),
                    }
                )
            else:
                merged.append(item)
        return merged

    @classmethod
    def _validate_binding_commitments(
        cls,
        *,
        generated_commitments: list[dict],
        commitments_input: list[dict],
    ) -> tuple[list[dict], dict | None]:
        expected_ids = [item["id"] for item in generated_commitments]
        if not expected_ids:
            return [], None

        if not commitments_input:
            return [], {
                "error": "validation_error",
                "code": "binding_commitments_incomplete",
                "details": {
                    "commitments": ["All generated commitment items must be explicitly accepted before finalize."],
                    "missing_commitment_ids": expected_ids,
                },
                "status": 400,
            }

        seen: set[str] = set()
        duplicates: list[str] = []
        by_id: dict[str, dict] = {}
        for item in commitments_input:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            if item_id in seen:
                duplicates.append(item_id)
                continue
            seen.add(item_id)
            by_id[item_id] = item

        unknown_ids = sorted([item_id for item_id in by_id if item_id not in expected_ids])
        missing_ids = sorted([item_id for item_id in expected_ids if item_id not in by_id])
        invalid_decisions = sorted(
            [
                item_id
                for item_id, item in by_id.items()
                if item_id in expected_ids and item.get("decision") != "accepted"
            ]
        )
        if duplicates or unknown_ids or missing_ids or invalid_decisions:
            details = {
                "commitments": ["Every generated commitment item must be present exactly once and explicitly accepted."],
            }
            if duplicates:
                details["duplicate_commitment_ids"] = sorted(list(set(duplicates)))
            if unknown_ids:
                details["unknown_commitment_ids"] = unknown_ids
            if missing_ids:
                details["missing_commitment_ids"] = missing_ids
            if invalid_decisions:
                details["non_accepted_commitment_ids"] = invalid_decisions
            return [], {
                "error": "validation_error",
                "code": "binding_commitments_incomplete",
                "details": details,
                "status": 400,
            }

        accepted = []
        generated_by_id = {item["id"]: item for item in generated_commitments}
        for item_id in expected_ids:
            accepted.append(
                {
                    **generated_by_id[item_id],
                    "decision": "accepted",
                }
            )
        return accepted, None

    @classmethod
    def _build_goal_contract_snapshot(
        cls,
        *,
        goal_payload: dict,
        user,
        accepted_commitments: list[dict],
    ) -> dict:
        return cls.CONTRACT_TEMPLATE_SERVICE.render_snapshot(
            goal_data=goal_payload,
            user=user,
            signed_name=str(goal_payload["signed_name"]).strip(),
            signed_at=goal_payload["signed_at"],
            accepted_gie_commitments=accepted_commitments,
        )

    @staticmethod
    def _build_commitment_statements_from_context(*, plan_payload: dict, unified_context: dict) -> tuple[str, str]:
        slot_profile = unified_context.get("slot_profile", {})
        goal_details = unified_context.get("goal_details", {})
        timeline = unified_context.get("timeline", {})
        goal_domain = str(slot_profile.get("goal_domain") or "").strip().lower()

        target_date = str(
            timeline.get("end_date")
            or (plan_payload.get("milestones") or [{}])[0].get("target_date")
            or "your target date"
        )
        goal_title = str(goal_details.get("title") or "").strip().rstrip(".")
        if not goal_title:
            goal_title = str(plan_payload.get("goal_summary") or "this goal").strip().rstrip(".")
        measurable_target = str(goal_details.get("measurable_target") or "").strip().rstrip(".")
        goal_reference = measurable_target or goal_title or "this goal"
        personal_reason = GIEPlanningService._commitment_personal_reason(slot_profile=slot_profile, goal_details=goal_details)

        if goal_domain == "running_endurance":
            weekly_training_days = GIEPlanningService._as_number_phrase(slot_profile.get("weekly_training_days"), fallback="planned")
            daily_session_minutes = GIEPlanningService._as_number_phrase(slot_profile.get("daily_session_minutes"), fallback="planned")
            primary = (
                f"I commit to completing my {weekly_training_days} running sessions each week for {daily_session_minutes} "
                f"minutes per session so I can achieve {goal_reference} by {target_date}."
            )
            weekly_review = (
                "I commit to reviewing my training every Sunday, adjusting my upcoming week based on missed sessions "
                f"or recovery signals so I stay on track for {goal_reference} by {target_date}."
            )
            return primary, weekly_review

        if goal_domain == "finance":
            savings_target = slot_profile.get("savings_target")
            monthly_income = slot_profile.get("monthly_income")
            monthly_fixed_expenses = slot_profile.get("monthly_fixed_expenses")
            existing_debt = slot_profile.get("existing_debt")
            monthly_capacity = None
            if isinstance(monthly_income, (int, float)) and isinstance(monthly_fixed_expenses, (int, float)):
                monthly_capacity = float(monthly_income) - float(monthly_fixed_expenses)
                if isinstance(existing_debt, (int, float)):
                    monthly_capacity -= float(existing_debt)
            transfer_amount = (
                f"{int(round(monthly_capacity))}"
                if isinstance(monthly_capacity, (int, float))
                else "my planned transfer amount"
            )
            primary = (
                f"I commit to transferring {transfer_amount} toward my savings goal on the 1st of every month so I can "
                f"reach {goal_reference} by {target_date}."
            )
            weekly_review = (
                "I commit to a 10-minute spending review every Sunday to verify my saving rate and adjust discretionary "
                f"spending to stay on track for {goal_reference} by {target_date}."
            )
            if isinstance(savings_target, (int, float)):
                primary = (
                    f"I commit to transferring {transfer_amount} toward my {int(round(float(savings_target)))} savings "
                    f"target on the 1st of every month so I can reach it by {target_date}."
                )
            return primary, weekly_review

        if goal_domain == "nutrition":
            prep_days = GIEPlanningService._as_number_phrase(slot_profile.get("meal_prep_days_per_week"), fallback="planned")
            meals_per_day = GIEPlanningService._as_number_phrase(slot_profile.get("meals_to_prepare_per_day"), fallback="planned")
            protein_target = GIEPlanningService._as_number_phrase(slot_profile.get("protein_goal_grams_per_day"), fallback="my")
            prep_minutes = GIEPlanningService._as_number_phrase(slot_profile.get("prep_time_per_day_minutes"), fallback="planned")
            constraints = GIEPlanningService._as_string(
                slot_profile.get("dietary_constraints"),
                fallback="my dietary constraints",
            ).rstrip(".")
            primary = (
                f"I commit to meal-prepping {meals_per_day} meals per day on {prep_days} days each week, spending "
                f"{prep_minutes} minutes per prep day, so I can consistently hit {protein_target}g protein by {target_date}."
            )
            weekly_review = (
                f"I commit to a weekly nutrition review every Sunday to adjust my meal plan around {constraints} and keep "
                f"steady progress toward {goal_reference} by {target_date}."
            )
            return primary, weekly_review

        if goal_domain == "skill_acquisition":
            daily_practice_minutes = GIEPlanningService._as_number_phrase(slot_profile.get("daily_practice_minutes"), fallback="planned")
            learning_method = GIEPlanningService._as_string(slot_profile.get("learning_method"), fallback="the learning method I committed to")
            milestone_event = GIEPlanningService._as_string(slot_profile.get("goal_milestone_event"), fallback=goal_reference)
            milestone_reference = str(milestone_event or goal_reference).strip().rstrip(".")
            primary = (
                f"I commit to practicing for {daily_practice_minutes} minutes every day using {learning_method}, so I can "
                f"deliver {milestone_reference} by {target_date}."
            )
            weekly_review = (
                "I commit to a weekly Sunday review to track completed practice sessions, identify bottlenecks, and "
                f"update next week's practice plan so I stay on course for {milestone_reference} by {target_date}."
            )
            return primary, weekly_review

        gap_focus = GIEPlanningService._as_string(
            slot_profile.get("manager_feedback_on_gaps"),
            fallback=personal_reason,
        ).rstrip(".")
        opportunities = GIEPlanningService._as_string(
            slot_profile.get("available_opportunities"),
            fallback="the opportunities already available to me",
        ).rstrip(".")
        primary = (
            f"I commit to two focused growth sessions each week on {gap_focus}, applying the work through {opportunities}, "
            f"so I can achieve {goal_reference} by {target_date}."
        )
        weekly_review = (
            "I commit to a Friday review every week to document progress, update my next actions, and keep momentum "
            f"toward {goal_reference} by {target_date}."
        )
        return primary, weekly_review

    @staticmethod
    def _as_string(value, *, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
        return fallback

    @staticmethod
    def _as_number_phrase(value, *, fallback: str) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(int(round(value)))
        return fallback

    @staticmethod
    def _commitment_personal_reason(*, slot_profile: dict, goal_details: dict) -> str:
        candidates = (
            slot_profile.get("motivation_driver"),
            slot_profile.get("savings_purpose"),
            slot_profile.get("dietary_constraints"),
            slot_profile.get("manager_feedback_on_gaps"),
            slot_profile.get("learning_method"),
            goal_details.get("why"),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "my confirmed motivation and constraints"

    @classmethod
    def _validate_habit_confirmations(
        cls,
        *,
        ranked_habit_suggestions: list[dict],
        habit_confirmations_input: list[dict],
    ) -> tuple[list[dict], dict | None]:
        expected_names = [
            item.get("habit_name")
            for item in ranked_habit_suggestions
            if isinstance(item, dict) and isinstance(item.get("habit_name"), str)
        ]
        expected_names = [name for name in expected_names if name]
        if not expected_names:
            return [], None

        if not habit_confirmations_input:
            return [], None

        seen = set()
        duplicates: list[str] = []
        confirmation_by_name: dict[str, dict] = {}
        for item in habit_confirmations_input:
            name = item.get("habit_name")
            if not isinstance(name, str):
                continue
            if name in seen:
                duplicates.append(name)
                continue
            seen.add(name)
            confirmation_by_name[name] = item

        invalid_names = sorted([name for name in confirmation_by_name if name not in expected_names])
        missing_names = sorted([name for name in expected_names if name not in confirmation_by_name])
        if duplicates or invalid_names or missing_names:
            details = {
                "habit_confirmations": ["Invalid confirmation set for ranked habit suggestions."],
                "suggested_habit_names": expected_names,
            }
            if duplicates:
                details["duplicate_habit_names"] = sorted(list(set(duplicates)))
            if invalid_names:
                details["invalid_habit_names"] = invalid_names
            if missing_names:
                details["missing_habit_names"] = missing_names
            return [], {
                "error": "validation_error",
                "code": "invalid_habit_confirmation_payload",
                "details": details,
                "status": 400,
            }

        normalized = []
        for name in expected_names:
            normalized.append(
                {
                    "habit_name": name,
                    "decision": confirmation_by_name[name]["decision"],
                }
            )
        return normalized, None

    @classmethod
    def _estimate_daily_capacity_minutes(cls, *, slot_states: list[GIESlotState]) -> int:
        state_by_key = {state.slot_key: state for state in slot_states}
        weekly_capacity = 4.0
        direct_daily_minutes = None
        for daily_key in ("daily_practice_minutes", "daily_session_minutes", "prep_time_per_day_minutes"):
            daily_state = state_by_key.get(daily_key)
            if daily_state and isinstance(daily_state.value, (int, float)):
                direct_daily_minutes = int(round(float(daily_state.value)))
                break
        if direct_daily_minutes is not None:
            return max(0, direct_daily_minutes)
        for key in cls.CAPACITY_SLOT_KEYS:
            state = state_by_key.get(key)
            if state and isinstance(state.value, (int, float)):
                weekly_capacity = float(state.value)
                break
        return max(0, int(round((weekly_capacity * 60) / 7)))

    @classmethod
    def _resolve_goal_priority(cls, *, slot_states: list[GIESlotState], unified_context: dict) -> str:
        state_by_key = {state.slot_key: state for state in slot_states}
        for key in cls.PRIORITY_SLOT_KEYS:
            state = state_by_key.get(key)
            if not state or not isinstance(state.value, str):
                continue
            normalized = state.value.strip().lower()
            if normalized in {"low", "medium", "high"}:
                return normalized

        raw_goal_text = str(unified_context.get("raw_goal") or "").strip().lower()
        slot_profile = unified_context.get("slot_profile", {})
        motivation_text = str(
            slot_profile.get("motivation_driver")
            or slot_profile.get("savings_purpose")
            or slot_profile.get("dietary_constraints")
            or ""
        ).strip().lower()
        combined_text = f"{raw_goal_text} {motivation_text}".strip()

        explicit_target_days = cls._days_to_explicit_target(slot_states=slot_states)
        has_event_deadline_signal = any(token in combined_text for token in cls.EVENT_DEADLINE_TOKENS)
        has_high_importance_signal = any(token in combined_text for token in cls.HIGH_IMPORTANCE_TOKENS)
        is_exploratory = any(token in combined_text for token in cls.EXPLORATORY_TOKENS)

        # High priority: specific event deadlines, <6 month timeline, or user-stated high importance.
        if has_event_deadline_signal or has_high_importance_signal:
            return "high"

        if explicit_target_days is not None:
            if explicit_target_days <= 183:
                return "high"
            if explicit_target_days <= 365:
                return "medium"
            return "medium"

        # Low priority: exploratory/vague intent with no explicit timeline.
        if is_exploratory:
            return "low"

        # Medium priority: open-ended goals with no explicit timeline.
        return "medium"

    @classmethod
    def _days_to_explicit_target(cls, *, slot_states: list[GIESlotState]) -> int | None:
        state_by_key = {state.slot_key: state for state in slot_states}
        for slot_key in cls.PRIORITY_DATE_SLOT_KEYS:
            state = state_by_key.get(slot_key)
            if not state or state.status not in {GIESlotState.STATUS_FILLED, GIESlotState.STATUS_LOCKED}:
                continue
            value = state.value
            if not isinstance(value, str):
                continue
            try:
                target_date = timezone.datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                continue
            return max(0, (target_date - timezone.localdate()).days)
        return None

    @classmethod
    def build_rie_signal(
        cls,
        *,
        slot_states: list[GIESlotState],
        unified_context: dict,
        ranked_habit_suggestions: list[dict],
        habit_confirmations: list[dict],
    ) -> dict:
        ranked_by_name = {
            item.get("habit_name"): item
            for item in ranked_habit_suggestions
            if isinstance(item, dict) and isinstance(item.get("habit_name"), str)
        }
        confirmed_habits: list[dict] = []
        for order_index, confirmation in enumerate(habit_confirmations, start=1):
            if confirmation.get("decision") != "accepted":
                continue
            habit_name = confirmation["habit_name"]
            ranked_item = ranked_by_name.get(habit_name, {})
            confirmed_habits.append(
                {
                    "habit_name": habit_name,
                    "rationale": ranked_item.get("rationale", ""),
                    "suggested_order": order_index,
                }
            )

        suggested_sequence_order = [item["habit_name"] for item in confirmed_habits]
        return {
            "goal_priority": cls._resolve_goal_priority(slot_states=slot_states, unified_context=unified_context),
            "confirmed_habits": confirmed_habits,
            "suggested_sequence_order": suggested_sequence_order,
            "estimated_daily_capacity_minutes": cls._estimate_daily_capacity_minutes(slot_states=slot_states),
        }

    @staticmethod
    def run_finalize_bridge(
        *,
        session: GIESession,
        goal_payload: dict,
    ) -> GIEFinalizeBridgeResult:
        request_payload = {
            "title": goal_payload["title"],
            "description": goal_payload["description"],
            "primary_category": resolve_canonical_category(
                goal_payload.get("primary_category"),
                goal_payload.get("category_pillar"),
                goal_payload.get("title", ""),
                goal_payload.get("description", ""),
            ),
            "priority": goal_payload["priority"],
            "target_date": goal_payload["target_date"],
            "why_it_matters": goal_payload["why_it_matters"],
            "why_do_i_want_this": goal_payload["why_do_i_want_this"],
            "specific_measurable_target": goal_payload["specific_measurable_target"],
            "commitment_confirmed": goal_payload["commitment_confirmed"],
            "commitment_intent": goal_payload["commitment_intent"],
            "commitment_effort": goal_payload["commitment_effort"],
            "commitment_responsibility": goal_payload["commitment_responsibility"],
            "signed_name": goal_payload["signed_name"],
            "signed_at": goal_payload["signed_at"],
            "contract_snapshot": goal_payload["contract_snapshot"],
        }
        factory = APIRequestFactory()
        request = factory.post("/goal/create-with-hierarchy/", request_payload, format="json")
        force_authenticate(request, user=session.user)

        try:
            response = CreateGoalWithHierarchyAPIView.as_view()(request)
            response.render()
            payload = getattr(response, "data", {})
            status_code = int(getattr(response, "status_code", 500))
            return GIEFinalizeBridgeResult(ok=(200 <= status_code < 300), status_code=status_code, payload=payload or {})
        except Exception as exc:
            return GIEFinalizeBridgeResult(
                ok=False,
                status_code=500,
                payload={"error": "bridge_exception", "message": str(exc)},
            )

    @classmethod
    def finalize_session(
        cls,
        *,
        session: GIESession,
        commitments_input: list[dict],
        habit_confirmations_input: list[dict],
        form_goal_context: dict | None = None,
    ) -> tuple[GIEPlanSnapshot | None, list[dict], dict, GIEFinalizeBridgeResult | None, dict | None, dict]:
        slot_states = list(session.slot_states.all().order_by("slot_key"))
        completeness = GIETurnPipelineService.compute_completeness_from_states(slot_states)
        if completeness["missing_required_slot_keys"]:
            return None, [], {}, None, {
                "error": "validation_error",
                "code": "required_slots_missing",
                "details": {"missing_required_slot_keys": completeness["missing_required_slot_keys"]},
                "status": 400,
            }, {"is_feasible": True, "warnings": [], "details": {}}

        ranked_habit_suggestions, _ = cls.ensure_ranked_habit_suggestions(session=session)
        normalized_habit_confirmations, habit_confirmation_error = cls._validate_habit_confirmations(
            ranked_habit_suggestions=ranked_habit_suggestions,
            habit_confirmations_input=habit_confirmations_input,
        )
        if habit_confirmation_error:
            return None, [], {}, None, habit_confirmation_error, {"is_feasible": True, "warnings": [], "details": {}}

        slot_states = list(session.slot_states.all().order_by("slot_key"))
        unified_context = GIEUnifiedContextService.build(session=session, slot_states=slot_states)
        if unified_context["slot_profile"]["completion_status"] != "complete":
            return None, [], {}, None, {
                "error": "validation_error",
                "code": "slot_profile_incomplete",
                "details": {"slot_profile": ["Unified context slot_profile must be complete before finalize."]},
                "status": 400,
            }, {"is_feasible": True, "warnings": [], "details": {}}

        feasibility_result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=slot_states,
            unified_context=unified_context,
        )
        feasibility_payload = {
            "is_feasible": bool(feasibility_result.get("feasible", False)),
            "warnings": [] if feasibility_result.get("feasible", False) else [str(feasibility_result.get("reason") or "Timeline may be infeasible for this plan.")],
            "details": feasibility_result,
        }

        plan_payload = cls.build_plan_payload(session=session, slot_states=slot_states, unified_context=unified_context)
        commitments = cls.materialize_commitments(
            commitments_input=commitments_input,
            plan_payload=plan_payload,
            unified_context=unified_context,
        )
        accepted_commitments, commitment_error = cls._validate_binding_commitments(
            generated_commitments=commitments,
            commitments_input=commitments_input,
        )
        if commitment_error:
            return None, commitments, {}, None, commitment_error, feasibility_payload
        resolved_goal_context = form_goal_context if isinstance(form_goal_context, dict) else {}
        resolved_priority = cls._resolve_goal_priority(slot_states=slot_states, unified_context=unified_context)
        goal_payload = cls.build_goal_autofill_payload(
            session=session,
            unified_context=unified_context,
            slot_states=slot_states,
            resolved_priority=resolved_priority,
            form_goal_context=form_goal_context,
            refine_language=True,
        )
        explicit_title = resolved_goal_context.get("title")
        if not (isinstance(explicit_title, str) and explicit_title.strip()):
            goal_payload["title"] = session.goal_text.strip()[:255]
        for field in (
            "commitment_confirmed",
            "commitment_intent",
            "commitment_effort",
            "commitment_responsibility",
            "signed_name",
            "signed_at",
        ):
            goal_payload[field] = resolved_goal_context.get(field)
        expected_snapshot = cls._build_goal_contract_snapshot(
            goal_payload=goal_payload,
            user=session.user,
            accepted_commitments=accepted_commitments,
        )
        provided_snapshot = resolved_goal_context.get("contract_snapshot")
        if provided_snapshot not in (None, "") and not cls.CONTRACT_TEMPLATE_SERVICE.validate_snapshot_matches(
            expected_snapshot=expected_snapshot,
            provided_snapshot=provided_snapshot,
        ):
            return None, commitments, {}, None, {
                "error": "validation_error",
                "code": "contract_snapshot_mismatch",
                "details": {
                    "contract_snapshot": [
                        "Provided contract snapshot does not match the required template-rendered commitment contract."
                    ]
                },
                "status": 400,
            }, feasibility_payload
        goal_payload["contract_snapshot"] = expected_snapshot
        missing_required_goal_fields = list_missing_required_goal_fields(goal_payload)
        if missing_required_goal_fields:
            return None, commitments, {}, None, {
                "error": "validation_error",
                "code": "required_goal_fields_missing",
                "details": {
                    "missing_required_goal_fields": missing_required_goal_fields,
                    "field_errors": required_goal_fields_error_details(missing_required_goal_fields),
                },
                "status": 400,
            }, feasibility_payload

        rie_signal = cls.build_rie_signal(
            slot_states=slot_states,
            unified_context=unified_context,
            ranked_habit_suggestions=ranked_habit_suggestions,
            habit_confirmations=normalized_habit_confirmations,
        )
        bridge_result = cls.run_finalize_bridge(
            session=session,
            goal_payload=goal_payload,
        )
        if not bridge_result.ok:
            downstream_payload = bridge_result.payload if isinstance(bridge_result.payload, dict) else {}
            return None, commitments, {}, bridge_result, {
                "error": "conflict",
                "code": "finalize_bridge_failed",
                "details": {
                    "session_status": ["Session remains ready_to_finalize."],
                    "downstream_status": [str(bridge_result.status_code)],
                    "downstream_error": downstream_payload,
                },
                "status": 409,
            }, feasibility_payload

        with transaction.atomic():
            locked_session = GIESession.objects.select_for_update().get(pk=session.pk)

            GIEPlanSnapshot.objects.filter(
                session=locked_session,
                status=GIEPlanSnapshot.STATUS_FINALIZED,
            ).update(status=GIEPlanSnapshot.STATUS_SUPERSEDED)

            snapshot = GIEPlanSnapshot.objects.create(
                session=locked_session,
                status=GIEPlanSnapshot.STATUS_FINALIZED,
                goal_summary=plan_payload["goal_summary"],
                assumptions=plan_payload["assumptions"],
                risks=plan_payload["risks"],
                milestones=plan_payload["milestones"],
                weekly_routine_guidance=plan_payload["weekly_routine_guidance"],
                rie_signal=rie_signal,
            )

            locked_session.status = GIESession.STATUS_FINALIZED
            locked_session.phase = GIESession.PHASE_FINALIZED
            locked_session.current_question = None
            locked_session.finalized_at = timezone.now()
            locked_session.save(update_fields=["status", "phase", "current_question", "finalized_at", "updated_at"])

        return snapshot, accepted_commitments, rie_signal, bridge_result, None, feasibility_payload
