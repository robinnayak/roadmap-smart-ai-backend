import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from django.utils import timezone

from goal.services.category_resolver import DEFAULT_GOAL_CATEGORY, normalize_goal_category


CONTRACT_SNAPSHOT_VERSION = "wave2.v1"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "commitment"
SHARED_TEMPLATE_PATH = TEMPLATES_DIR / "_shared.json"


class GoalContractTemplateService:
    def __init__(self) -> None:
        self._shared_template = self._load_template("_shared")

    def render_snapshot(
        self,
        *,
        goal_data,
        user,
        signed_name: str,
        signed_at,
        accepted_gie_commitments: list[dict] | None = None,
    ) -> dict:
        normalized_goal = self._normalize_goal_data(goal_data)
        category = normalized_goal["category"]
        category_template = self._load_template(category)
        signed_at_value = self._normalize_datetime(signed_at)
        generated_at = timezone.now()
        accepted_commitments = self._normalize_accepted_commitments(accepted_gie_commitments)

        snapshot = {
            "version": CONTRACT_SNAPSHOT_VERSION,
            "category": category,
            "title": normalized_goal["title"],
            "generated_at": generated_at.isoformat(),
            "signed_name": signed_name.strip(),
            "signed_at": signed_at_value.isoformat(),
            "header": self._build_header(
                goal=normalized_goal,
                user=user,
                signed_name=signed_name.strip(),
                signed_at=signed_at_value,
            ),
            "sections": {
                "i_will": self._build_i_will(
                    goal=normalized_goal,
                    category_template=category_template,
                    accepted_commitments=accepted_commitments,
                ),
                "i_will_not": self._build_i_will_not(
                    category_template=category_template,
                ),
                "reality_anchors": self._build_reality_anchors(
                    category_template=category_template,
                ),
                "quit_anchors": self._build_quit_anchors(
                    goal=normalized_goal,
                    accepted_commitments=accepted_commitments,
                ),
                "closing_affirmations": list(self._shared_template["closing_affirmations"]),
            },
            "gie_commitments": accepted_commitments,
        }

        if normalized_goal["goal_id"]:
            snapshot["goal_id"] = normalized_goal["goal_id"]

        return snapshot

    def validate_snapshot_matches(
        self,
        *,
        expected_snapshot: dict,
        provided_snapshot,
    ) -> bool:
        return isinstance(provided_snapshot, Mapping) and dict(provided_snapshot) == expected_snapshot

    def _load_template(self, name: str) -> dict:
        template_path = SHARED_TEMPLATE_PATH if name == "_shared" else TEMPLATES_DIR / f"{name}.json"
        with template_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _normalize_goal_data(self, goal_data) -> dict:
        if hasattr(goal_data, "primary_category"):
            impact_dimensions = dict(getattr(goal_data, "impact_dimensions", {}) or {})
            target_date = getattr(goal_data, "target_date", None)
            start_date = getattr(goal_data, "start_date", None)
            financial_target_amount = getattr(goal_data, "financial_target_amount", None)
            financial_current_saved = getattr(goal_data, "financial_current_saved", None)
            raw = {
                "goal_id": str(getattr(goal_data, "id", "")) or None,
                "title": getattr(goal_data, "title", ""),
                "description": getattr(goal_data, "description", ""),
                "category": getattr(goal_data, "primary_category", None),
                "why_it_matters": getattr(goal_data, "why_it_matters", []),
                "why_do_i_want_this": impact_dimensions.get("why_do_i_want_this", ""),
                "specific_measurable_target": impact_dimensions.get("specific_measurable_target", ""),
                "start_date": start_date,
                "target_date": target_date,
                "financial_target_amount": financial_target_amount,
                "financial_current_saved": financial_current_saved,
            }
        else:
            impact_dimensions = dict(goal_data.get("impact_dimensions") or {})
            raw = {
                "goal_id": str(goal_data.get("id") or goal_data.get("goal_id") or "") or None,
                "title": str(goal_data.get("title") or "").strip(),
                "description": str(goal_data.get("description") or "").strip(),
                "category": goal_data.get("resolved_category") or goal_data.get("primary_category"),
                "why_it_matters": goal_data.get("why_it_matters") or [],
                "why_do_i_want_this": str(
                    goal_data.get("why_do_i_want_this") or impact_dimensions.get("why_do_i_want_this") or ""
                ).strip(),
                "specific_measurable_target": str(
                    goal_data.get("specific_measurable_target")
                    or impact_dimensions.get("specific_measurable_target")
                    or ""
                ).strip(),
                "start_date": goal_data.get("start_date"),
                "target_date": goal_data.get("target_date"),
                "financial_target_amount": goal_data.get("financial_target_amount"),
                "financial_current_saved": goal_data.get("financial_current_saved"),
            }

        why_it_matters = raw["why_it_matters"]
        if isinstance(why_it_matters, str):
            reasons = [item.strip() for item in why_it_matters.splitlines() if item.strip()]
        else:
            reasons = [str(item).strip() for item in why_it_matters if str(item).strip()]

        raw["why_it_matters"] = reasons
        raw["category"] = normalize_goal_category(str(raw["category"] or DEFAULT_GOAL_CATEGORY).strip().lower()) or DEFAULT_GOAL_CATEGORY
        raw["start_date"] = self._normalize_date(raw["start_date"])
        raw["target_date"] = self._normalize_date(raw["target_date"])
        return raw

    def _build_header(self, *, goal: dict, user, signed_name: str, signed_at: datetime) -> dict:
        display_name = ""
        if hasattr(user, "get_full_name"):
            display_name = user.get_full_name().strip()
        display_name = display_name or getattr(user, "email", "") or signed_name
        start_date = goal["start_date"] or signed_at.date()
        target_date = goal["target_date"]
        days_remaining = (target_date - signed_at.date()).days if target_date else None
        return {
            "user_display_name": display_name,
            "signed_name": signed_name,
            "signed_at": signed_at.isoformat(),
            "start_date": start_date.isoformat() if start_date else None,
            "target_date": target_date.isoformat() if target_date else None,
            "days_remaining": days_remaining,
            "goal_title": goal["title"],
        }

    def _build_i_will(self, *, goal: dict, category_template: dict, accepted_commitments: list[dict]) -> list[str]:
        items: list[str] = []
        if accepted_commitments:
            items.extend(item["statement"] for item in accepted_commitments)

        measurable_target = goal["specific_measurable_target"]
        if measurable_target:
            items.append(f"I will execute toward this concrete target: {measurable_target}.")

        for reason in goal["why_it_matters"][:2]:
            items.append(f"I will protect time for this goal because it matters for {reason}.")

        if goal["description"]:
            items.append(f"I will stay aligned with the real work described in this goal: {goal['description']}.")

        if goal["category"] == "finance" and goal["financial_target_amount"] is not None:
            items.append(
                f"I will track progress against my financial target of {goal['financial_target_amount']} and close the gap deliberately."
            )

        if not items:
            items.extend(category_template.get("will_defaults", []))

        return self._dedupe_preserve_order(items)

    def _build_i_will_not(self, *, category_template: dict) -> list[str]:
        return self._dedupe_preserve_order(category_template.get("will_not", []))

    def _build_reality_anchors(self, *, category_template: dict) -> list[str]:
        return self._dedupe_preserve_order(
            list(self._shared_template["reality_anchors"]) + list(category_template.get("reality_anchors", []))
        )

    def _build_quit_anchors(self, *, goal: dict, accepted_commitments: list[dict]) -> list[str]:
        anchors: list[str] = []
        if goal["why_do_i_want_this"]:
            anchors.append(f"When I want to quit, I will remember why this matters: {goal['why_do_i_want_this']}.")
        for reason in goal["why_it_matters"][:3]:
            anchors.append(f"When I want to quit, I will remember that this supports {reason}.")
        if goal["specific_measurable_target"]:
            anchors.append(f"When I want to quit, I will remember the target I chose: {goal['specific_measurable_target']}.")
        if goal["category"] == "finance" and goal["financial_target_amount"] is not None:
            anchors.append(
                f"When I want to quit, I will remember the amount I committed to reach: {goal['financial_target_amount']}."
            )
        for item in accepted_commitments[:2]:
            anchors.append(f"When I want to quit, I will remember the promise I accepted: {item['title']}.")
        if not anchors:
            anchors.extend(self._shared_template["quit_anchor_defaults"])
        return self._dedupe_preserve_order(anchors)

    def _normalize_accepted_commitments(self, commitments: list[dict] | None) -> list[dict]:
        normalized: list[dict] = []
        for item in commitments or []:
            normalized.append(
                {
                    "id": str(item["id"]),
                    "title": str(item["title"]).strip(),
                    "statement": str(item["statement"]).strip(),
                    "linked_milestone_title": str(item.get("linked_milestone_title") or "").strip(),
                    "decision": "accepted",
                }
            )
        return normalized

    def _normalize_datetime(self, value) -> datetime:
        if isinstance(value, datetime):
            return value
        candidate = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(candidate)

    def _normalize_date(self, value) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _dedupe_preserve_order(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized
