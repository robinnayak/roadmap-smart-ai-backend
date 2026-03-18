from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from django.utils import timezone

from ai.utils.parsers import ResponseParser
from goal.models import Goal, UserFinancialProfile
from goal.services.timeline_ai_provider import get_timeline_ai_provider_adapter
from goal.services.timeline_conflict_detector import detect_goal_conflicts
from goal.services.timeline_deterministic import compute_timeline_realism
from goal.services.timeline_insight_contract import assert_no_gie_runtime_dependency
from goal.services.timeline_similar_goal_detector import detect_similar_goals


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "ai" / "prompts" / "timeline_insight"


@dataclass(frozen=True)
class GoalInsightPayload:
    feasibility: dict
    missing_elements: list[str]
    conflicts: list[str]

    def as_dict(self) -> dict:
        return {
            "feasibility": self.feasibility,
            "missing_elements": self.missing_elements,
            "conflicts": self.conflicts,
        }


class GoalTimelineInsightService:
    REALISTIC_IMPACT_THRESHOLD = 85.0
    STRETCH_IMPACT_THRESHOLD = 60.0
    VALID_STATUSES = {"realistic", "stretch", "unrealistic"}

    def get_or_create_cached_insight(self, *, user, goal: Goal) -> dict:
        active_goals = list(
            Goal.objects.filter(user=user)
            .exclude(status__in=("completed", "cancelled"))
            .exclude(id=goal.id)
            .order_by("target_date", "created_at")
        )
        health_profile = self._get_latest_health_profile(user=user)
        finance_profile = self._get_finance_profile(user=user, goal=goal)
        fingerprint = self._build_fingerprint(
            goal=goal,
            active_goals=active_goals,
            health_profile=health_profile,
            finance_profile=finance_profile,
        )
        cached_payload = goal.timeline_insight_payload
        if (
            goal.timeline_insight_fingerprint == fingerprint
            and isinstance(cached_payload, dict)
        ):
            return cached_payload

        payload = self._analyze(
            user=user,
            goal=goal,
            active_goals=active_goals,
            health_profile=health_profile,
            finance_profile=finance_profile,
        )
        goal.timeline_insight_payload = payload
        goal.timeline_insight_fingerprint = fingerprint
        goal.timeline_insight_generated_at = timezone.now()
        goal.save(
            update_fields=[
                "timeline_insight_payload",
                "timeline_insight_fingerprint",
                "timeline_insight_generated_at",
            ]
        )
        return payload

    def analyze(self, *, user, goal: Goal) -> dict:
        return self._analyze(
            user=user,
            goal=goal,
            active_goals=None,
            health_profile=None,
            finance_profile=None,
        )

    def _analyze(
        self,
        *,
        user,
        goal: Goal,
        active_goals: list[Goal] | None,
        health_profile,
        finance_profile,
    ) -> dict:
        assert_no_gie_runtime_dependency(
            [
                "goal.services.timeline_insight_service",
                "goal.services.timeline_deterministic",
            ]
        )
        if active_goals is None:
            active_goals = list(
                Goal.objects.filter(user=user)
                .exclude(status__in=("completed", "cancelled"))
                .exclude(id=goal.id)
                .order_by("target_date", "created_at")
            )
        if health_profile is None:
            health_profile = self._get_latest_health_profile(user=user)
        if finance_profile is None:
            finance_profile = self._get_finance_profile(user=user, goal=goal)
        context = self._build_analysis_context(
            goal=goal,
            active_goals=active_goals,
            health_profile=health_profile,
            finance_profile=finance_profile,
        )
        feasibility = self._build_feasibility(goal=goal, context=context, health_profile=health_profile)
        missing_elements = self._detect_missing_structure(goal=goal)
        fallback_payload = GoalInsightPayload(
            feasibility=feasibility,
            missing_elements=missing_elements,
            conflicts=[],
        )
        try:
            provider_adapter = get_timeline_ai_provider_adapter()
        except Exception:
            return fallback_payload.as_dict()
        similar_findings = detect_similar_goals(
            current_goal=context["current_goal"],
            active_goals=context["active_goals"],
            provider_adapter=provider_adapter,
        )
        conflict_findings = detect_goal_conflicts(
            current_goal=context["current_goal"],
            active_goals=context["active_goals"],
            provider_adapter=provider_adapter,
        )
        semantic_findings = self._dedupe_strings([*similar_findings, *conflict_findings], limit=5)
        fallback_payload = GoalInsightPayload(
            feasibility=feasibility,
            missing_elements=missing_elements,
            conflicts=semantic_findings,
        )
        ai_payload = self._generate_ai_payload(
            provider_adapter=provider_adapter,
            context=context,
            fallback_payload=fallback_payload,
            semantic_findings=semantic_findings,
        )
        if ai_payload is not None:
            return ai_payload
        return fallback_payload.as_dict()

    def _build_fingerprint(self, *, goal: Goal, active_goals: list[Goal], health_profile, finance_profile) -> str:
        payload = {
            "current_goal": self._normalize_goal_cache_input(goal),
            "active_goals": [self._normalize_goal_cache_input(item) for item in active_goals],
            "health_profile_updated_at": self._serialize_datetime(getattr(health_profile, "updated_at", None)),
            "finance_profile_updated_at": self._serialize_datetime(getattr(finance_profile, "updated_at", None)),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_latest_health_profile(*, user):
        try:
            from routine.models import HealthProfile
        except Exception:
            return None
        return HealthProfile.objects.filter(user=user).order_by("-updated_at").first()

    @staticmethod
    def _get_finance_profile(*, user, goal: Goal):
        if goal.primary_category != "finance":
            return None
        return UserFinancialProfile.objects.filter(user=user).first()

    @staticmethod
    def _goal_domain_from_category(category: str) -> str:
        if category in {"finance"}:
            return "financial"
        if category in {"fitness", "wellness", "nutrition", "health"}:
            return "health"
        if category in {"career"}:
            return "career"
        if category in {"business"}:
            return "business"
        if category in {"education", "learning"}:
            return "learning"
        return "personal"

    def _build_analysis_context(self, *, goal: Goal, active_goals: list[Goal], health_profile, finance_profile) -> dict:
        return {
            "current_goal": self._normalize_goal_context(goal),
            "active_goals": [self._normalize_goal_context(item) for item in active_goals],
            "health_profile_present": bool(health_profile),
            "finance_profile_present": bool(finance_profile),
        }

    def _build_feasibility(self, *, goal: Goal, context: dict, health_profile) -> dict:
        if not goal.target_date:
            return {
                "status": "stretch",
                "summary": "Set a target date to evaluate timeline realism and pace.",
                "achievable_version": None,
            }

        today = timezone.localdate()
        stated_timeline_days = max(1, (goal.target_date - today).days)
        slot_values = self._build_slot_values(goal=goal)
        realism = compute_timeline_realism(
            goal_domain=self._goal_domain_from_category(goal.primary_category),
            slot_values=slot_values,
            health_profile=health_profile,
            stated_timeline_days=stated_timeline_days,
            today=today,
        )
        status_value = self._map_status(realism["impact_percent"])
        if status_value == "realistic":
            summary = "Timeline looks realistic for your current pace and context."
        elif status_value == "stretch":
            summary = "Timeline is a stretch; consider scope adjustments to improve consistency."
        else:
            summary = "Timeline is likely unrealistic without extending dates or reducing scope."

        return {
            "status": status_value,
            "summary": summary,
            "achievable_version": realism["achievable_sub_goal"],
        }

    @staticmethod
    def _build_slot_values(*, goal: Goal) -> dict:
        values = {
            "timeline_target_date": goal.target_date.isoformat() if goal.target_date else None,
            "target_amount": float(goal.financial_target_amount) if goal.financial_target_amount is not None else None,
            "current_saved_amount": (
                float(goal.financial_current_saved) if goal.financial_current_saved is not None else None
            ),
            "monthly_saving_capacity": None,
        }
        return values

    def _map_status(self, impact_percent: float) -> str:
        if impact_percent >= self.REALISTIC_IMPACT_THRESHOLD:
            return "realistic"
        if impact_percent >= self.STRETCH_IMPACT_THRESHOLD:
            return "stretch"
        return "unrealistic"

    def _detect_missing_structure(self, *, goal: Goal) -> list[str]:
        missing: list[str] = []
        impact = goal.impact_dimensions or {}
        measurable_target = (impact.get("specific_measurable_target") or "").strip()
        if not measurable_target and goal.financial_target_amount is None:
            missing.append("No measurable target is defined yet.")

        if not goal.target_date:
            missing.append("No clear timeframe is set for completion.")

        if self._missing_baseline(goal=goal):
            missing.append("No clear baseline is available to measure progress from.")

        if self._is_low_specificity(goal=goal):
            missing.append("Goal details are too broad; add specific scope and constraints.")

        return missing

    @staticmethod
    def _missing_baseline(*, goal: Goal) -> bool:
        if goal.primary_category == "finance":
            return goal.financial_current_saved is None

        has_progress_entries = goal.progress_entries.exists()
        if has_progress_entries:
            return False

        if goal.primary_category in {"fitness", "wellness", "nutrition", "health"}:
            try:
                health_data = goal.attributes.health_data or {}
            except Exception:
                health_data = {}
            current_keys = [key for key in health_data.keys() if key.startswith("current_")]
            return len(current_keys) == 0

        return not bool(goal.description and goal.description.strip())

    @staticmethod
    def _is_low_specificity(*, goal: Goal) -> bool:
        title_tokens = [token for token in (goal.title or "").split() if token.strip()]
        description_text = (goal.description or "").strip()
        description_tokens = [token for token in description_text.split() if token.strip()]
        return len(title_tokens) < 3 or len(description_tokens) < 8

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = (text or "").lower()
        cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in lowered)
        return " ".join(cleaned.split())

    @staticmethod
    def _normalize_goal_context(goal: Goal) -> dict:
        return {
            "id": str(goal.id),
            "title": goal.title,
            "description": goal.description or "",
            "primary_category": goal.primary_category,
            "priority": goal.priority,
            "status": goal.status,
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
            "progress_percentage": int(goal.progress_percentage or 0),
        }

    @staticmethod
    def _normalize_goal_cache_input(goal: Goal) -> dict:
        return {
            "id": str(goal.id),
            "title": goal.title,
            "description": goal.description or "",
            "primary_category": goal.primary_category,
            "priority": goal.priority,
            "status": goal.status,
            "start_date": goal.start_date.isoformat() if goal.start_date else None,
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
            "progress_percentage": int(goal.progress_percentage or 0),
            "impact_dimensions": goal.impact_dimensions or {},
            "financial_target_amount": (
                str(goal.financial_target_amount) if goal.financial_target_amount is not None else None
            ),
            "financial_current_saved": (
                str(goal.financial_current_saved) if goal.financial_current_saved is not None else None
            ),
            "financial_goal_type": goal.financial_goal_type,
            "financial_timeline_flexibility": goal.financial_timeline_flexibility,
            "financial_feasibility_status": goal.financial_feasibility_status,
        }

    @staticmethod
    def _serialize_datetime(value) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    def _generate_ai_payload(self, *, provider_adapter, context: dict, fallback_payload: GoalInsightPayload, semantic_findings: list[str]) -> dict | None:
        prompt = self._build_final_prompt(
            context=context,
            fallback_payload=fallback_payload,
            semantic_findings=semantic_findings,
            repair=False,
        )
        system_prompt = self._load_prompt("system.txt")
        first_attempt = self._call_and_validate(
            provider_adapter=provider_adapter,
            prompt=prompt,
            system_prompt=system_prompt,
        )
        if first_attempt is not None:
            return first_attempt

        repair_prompt = self._build_final_prompt(
            context=context,
            fallback_payload=fallback_payload,
            semantic_findings=semantic_findings,
            repair=True,
        )
        return self._call_and_validate(
            provider_adapter=provider_adapter,
            prompt=repair_prompt,
            system_prompt=system_prompt,
        )

    def _call_and_validate(self, *, provider_adapter, prompt: str, system_prompt: str) -> dict | None:
        try:
            response = provider_adapter.generate_timeline_insight(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            parsed = ResponseParser.parse_json(response.content)
            return self._validate_goal_insight_payload(parsed)
        except Exception:
            return None

    def _build_final_prompt(self, *, context: dict, fallback_payload: GoalInsightPayload, semantic_findings: list[str], repair: bool) -> str:
        repair_rule = "STRICT REPAIR MODE: Return strict JSON only." if repair else ""
        return "\n\n".join(
            item
            for item in [
                "Create a read-only timeline insight payload for the current goal.",
                repair_rule,
                "CURRENT GOAL",
                self._render_goal_context(context["current_goal"]),
                "ACTIVE GOALS",
                self._render_goal_list(context["active_goals"]),
                f"HEALTH PROFILE PRESENT: {context['health_profile_present']}",
                f"FINANCE PROFILE PRESENT: {context['finance_profile_present']}",
                "DETERMINISTIC FEASIBILITY",
                str(fallback_payload.feasibility),
                "DETERMINISTIC MISSING ELEMENTS",
                self._render_string_list(fallback_payload.missing_elements),
                "SEMANTIC FINDINGS",
                self._render_string_list(semantic_findings),
                self._load_prompt("output_schema.txt"),
            ]
            if item
        )

    def _validate_goal_insight_payload(self, payload) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Timeline insight payload must be an object.")

        expected_keys = {"feasibility", "missing_elements", "conflicts"}
        if set(payload.keys()) != expected_keys:
            raise ValueError("Timeline insight payload keys do not match the contract.")

        feasibility = payload.get("feasibility")
        if not isinstance(feasibility, dict):
            raise ValueError("feasibility must be an object.")
        if set(feasibility.keys()) != {"status", "summary", "achievable_version"}:
            raise ValueError("feasibility keys do not match the contract.")
        if feasibility.get("status") not in self.VALID_STATUSES:
            raise ValueError("feasibility.status is invalid.")
        if not isinstance(feasibility.get("summary"), str):
            raise ValueError("feasibility.summary must be a string.")
        achievable_version = feasibility.get("achievable_version")
        if achievable_version is not None and not isinstance(achievable_version, str):
            raise ValueError("feasibility.achievable_version must be a string or null.")

        missing_elements = self._validate_string_list(payload.get("missing_elements"), field_name="missing_elements")
        conflicts = self._validate_string_list(payload.get("conflicts"), field_name="conflicts")

        return {
            "feasibility": {
                "status": feasibility["status"],
                "summary": feasibility["summary"].strip(),
                "achievable_version": achievable_version.strip() if isinstance(achievable_version, str) else None,
            },
            "missing_elements": missing_elements,
            "conflicts": conflicts,
        }

    @staticmethod
    def _validate_string_list(value, *, field_name: str) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list.")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} must contain only strings.")
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _dedupe_strings(items: list[str], *, limit: int) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            cleaned = (item or "").strip()
            if not cleaned or cleaned in seen:
                continue
            deduped.append(cleaned)
            seen.add(cleaned)
            if len(deduped) >= limit:
                break
        return deduped

    @staticmethod
    def _load_prompt(name: str) -> str:
        path = PROMPTS_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"Required timeline insight prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _render_goal_context(self, goal_context: dict) -> str:
        return (
            f"Title: {goal_context.get('title', '')}\n"
            f"Description: {goal_context.get('description', '')}\n"
            f"Category: {goal_context.get('primary_category', '')}\n"
            f"Priority: {goal_context.get('priority', '')}\n"
            f"Status: {goal_context.get('status', '')}\n"
            f"Target Date: {goal_context.get('target_date')}\n"
            f"Progress: {goal_context.get('progress_percentage', 0)}"
        )

    def _render_goal_list(self, goals: list[dict]) -> str:
        if not goals:
            return "No other active goals."
        return "\n\n".join(self._render_goal_context(goal) for goal in goals)

    @staticmethod
    def _render_string_list(items: list[str]) -> str:
        if not items:
            return "None."
        return "\n".join(f"- {item}" for item in items)
