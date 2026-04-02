from copy import deepcopy


class GIEDialogueManagerService:
    """
    Deterministic Step 4 question selection and next-prompt generation.
    """

    DEFAULT_SLOT_QUESTION_MAP = {
        "current_role": "What role are you in right now?",
        "target_role": "What role are you working toward?",
        "time_in_current_role": "How long have you been in it?",
        "target_timeline": "When do you want to make that move?",
        "manager_feedback_on_gaps": "What gaps have come up in feedback so far?",
        "available_opportunities": "What opportunities do you already have to grow?",
        "timeline_target_date": "What date are you aiming for?",
        "target_date": "What date are you aiming for?",
        "weekly_training_days": "How many days a week can you train?",
        "daily_session_minutes": "How long can each session be?",
        "current_fitness_baseline": "Where is your fitness starting from right now?",
        "running_experience": "What running experience do you already have?",
        "injury_constraints": "Any injuries or physical limits to work around?",
        "equipment_and_location": "What gear or training space do you have access to?",
        "current_nutrition_baseline": "What does your eating routine look like right now?",
        "meal_prep_days_per_week": "How many days a week can you prep?",
        "meals_to_prepare_per_day": "How many meals do you want to prep per day?",
        "protein_goal_grams_per_day": "What protein target do you want to hit each day?",
        "dietary_constraints": "Any dietary restrictions or foods you avoid?",
        "prep_time_per_day_minutes": "How much time can you spend on prep each day?",
        "motivation_driver": "Why does this goal matter to you right now?",
        "savings_target": "What amount are you trying to save?",
        "monthly_income": "What is your monthly income?",
        "monthly_fixed_expenses": "What do your fixed monthly expenses look like?",
        "current_savings": "How much have you already saved?",
        "existing_debt": "What debt payments are you carrying each month?",
        "savings_purpose": "What is this money for?",
        "current_skill_level": "Where would you say your skill level is right now?",
        "has_required_equipment": "Do you already have what you need to practice?",
        "preferred_style_or_genre": "Is there a style or direction you want to focus on?",
        "daily_practice_minutes": "How much time can you practice each day?",
        "goal_milestone_event": "What milestone would make this feel real?",
        "learning_method": "How do you want to learn or practice this?",
    }

    DOMAIN_SLOT_QUESTION_MAP = {
        "career": {
            "current_role": "What role are you in right now?",
            "target_role": "What role are you aiming for next?",
            "time_in_current_role": "How long have you been in your current role?",
            "target_timeline": "When do you want to make that move?",
            "manager_feedback_on_gaps": "What feedback have you gotten about the gaps to close?",
            "available_opportunities": "What projects, mentors, or opportunities can help you grow?",
        },
        "fitness": {
            "current_fitness_baseline": "What does your fitness base look like right now?",
            "running_experience": "How much running experience do you already have?",
            "weekly_training_days": "How many days a week can you realistically train?",
            "daily_session_minutes": "How much time can you give each workout?",
            "injury_constraints": "Any injuries or limits I should factor in?",
            "equipment_and_location": "Where will you train, and what equipment do you have?",
            "motivation_driver": "What is pushing you to do this now?",
            "timeline_target_date": "What date are you aiming for?",
        },
        "nutrition": {
            "current_nutrition_baseline": "What does your eating routine look like today?",
            "meal_prep_days_per_week": "How many days a week can you prep food?",
            "meals_to_prepare_per_day": "How many meals do you want ready each day?",
            "protein_goal_grams_per_day": "What daily protein goal are you aiming for?",
            "dietary_constraints": "Any dietary limits or food preferences to respect?",
            "prep_time_per_day_minutes": "How much time can you spend prepping each day?",
            "motivation_driver": "Why is this nutrition goal important right now?",
            "timeline_target_date": "What date are you aiming for?",
        },
        "finance": {
            "savings_target": "How much do you want to save?",
            "target_date": "By when do you want to hit that number?",
            "monthly_income": "What is your monthly take-home income?",
            "monthly_fixed_expenses": "What are your fixed monthly expenses?",
            "current_savings": "How much do you already have saved?",
            "existing_debt": "What debt payments do you make each month?",
            "savings_purpose": "What is this savings goal for?",
        },
        "learning": {
            "current_skill_level": "Where are you starting from with this skill?",
            "has_required_equipment": "Do you already have what you need to practice?",
            "preferred_style_or_genre": "Is there a style or direction you want to focus on?",
            "daily_practice_minutes": "How much time can you practice each day?",
            "goal_milestone_event": "What milestone would show real progress?",
            "learning_method": "How do you want to learn this best?",
            "timeline_target_date": "What date are you aiming for?",
        },
        "personal": {
            "motivation_driver": "What feels most important about this right now?",
            "timeline_target_date": "What date are you aiming for?",
        },
        "productivity": {
            "motivation_driver": "What is getting in the way most right now?",
            "timeline_target_date": "What date are you aiming for?",
        },
        "business": {
            "motivation_driver": "What outcome are you trying to create with this goal?",
            "timeline_target_date": "What date are you aiming for?",
        },
    }

    @classmethod
    def build_question(
        cls,
        *,
        slot_key: str,
        slot_label: str | None = None,
        slot_description: str | None = None,
        goal_text: str | None = None,
        goal_domain: str | None = None,
    ) -> str:
        """
        Build a slot question that stays deterministic but can include light
        context from schema metadata while staying concise and domain-aware.
        """
        prompt_domain = cls._resolve_prompt_domain(
            goal_domain=goal_domain,
            goal_text=goal_text,
            slot_key=slot_key,
        )
        base_question = cls.DOMAIN_SLOT_QUESTION_MAP.get(prompt_domain, {}).get(slot_key)
        if not base_question:
            base_question = cls.DEFAULT_SLOT_QUESTION_MAP.get(slot_key)
        if not base_question:
            if slot_description:
                cleaned = str(slot_description).strip().rstrip(".")
                base_question = f"{cleaned}?"
            else:
                label = (slot_label or slot_key.replace("_", " ")).strip().lower()
                base_question = f"What is your {label}?"
        return base_question

    @classmethod
    def build_initial_state(cls, schema: dict, intake_analysis: dict) -> dict:
        required_slots = deepcopy(schema.get("required_slots", []))
        optional_slots = deepcopy(schema.get("optional_slots", []))
        slot_state = []
        state_by_key = {}

        for slot in required_slots + optional_slots:
            state = {
                "slot_key": slot["key"],
                "required": bool(slot["required"]),
                "status": "missing",
                "value": None,
                "source": None,
                "confidence": None,
                "last_updated_turn_index": None,
                "missing_reason": "not_provided_yet",
            }
            slot_state.append(state)
            state_by_key[state["slot_key"]] = state

        cls._apply_deterministic_prefills(state_by_key, intake_analysis)

        completeness = cls._compute_completeness(required_slots, state_by_key)
        next_prompt = cls._select_next_prompt(
            required_slots,
            state_by_key,
            goal_text=(intake_analysis or {}).get("goal_text"),
            goal_domain=((intake_analysis or {}).get("goal_domain") or {}).get("value"),
        )

        return {
            "slot_state": slot_state,
            "completeness": completeness,
            "next_prompt": next_prompt,
        }

    @classmethod
    def _apply_deterministic_prefills(cls, state_by_key: dict, intake_analysis: dict):
        nlu = (intake_analysis or {}).get("nlu") or {}
        cadence = nlu.get("weekly_cadence")
        numeric_targets = nlu.get("numeric_targets") or []

        if cadence and isinstance(cadence.get("value"), int):
            cls._fill_slot(
                state_by_key,
                "weekly_training_days",
                cadence["value"],
                "goal_text",
                0.9,
            )
            cls._fill_slot(
                state_by_key,
                "meal_prep_days_per_week",
                cadence["value"],
                "goal_text",
                0.9,
            )
            cls._fill_slot(
                state_by_key,
                "practice_days_per_week",
                cadence["value"],
                "goal_text",
                0.75,
            )
            cls._fill_slot(
                state_by_key,
                "daily_practice_minutes",
                cadence["value"],
                "goal_text",
                0.5,
            )

        if numeric_targets:
            first_number = numeric_targets[0].get("value")
            if isinstance(first_number, (int, float)):
                cls._fill_slot(
                    state_by_key,
                    "savings_target",
                    float(first_number),
                    "goal_text",
                    0.65,
                )

    @staticmethod
    def _fill_slot(state_by_key: dict, slot_key: str, value, source: str, confidence: float):
        state = state_by_key.get(slot_key)
        if state is None or state.get("value") is not None:
            return
        state["status"] = "filled"
        state["value"] = value
        state["source"] = source
        state["confidence"] = confidence
        state["missing_reason"] = None

    @staticmethod
    def _compute_completeness(required_slots: list, state_by_key: dict) -> dict:
        required_keys = [slot["key"] for slot in required_slots]
        filled_required = [
            key
            for key in required_keys
            if state_by_key.get(key, {}).get("status") in ("filled", "locked")
        ]
        missing_required = [key for key in required_keys if key not in filled_required]
        required_count = len(required_keys)
        filled_count = len(filled_required)
        percent = round((filled_count / required_count) * 100, 2) if required_count else 100.0

        return {
            "required_slot_count": required_count,
            "filled_required_slot_count": filled_count,
            "completeness_percent": percent,
            "missing_required_slot_keys": missing_required,
        }

    @classmethod
    def _select_next_prompt(
        cls,
        required_slots: list,
        state_by_key: dict,
        *,
        goal_text: str | None = None,
        goal_domain: str | None = None,
    ) -> dict | None:
        for slot in required_slots:
            key = slot["key"]
            slot_state = state_by_key.get(key, {})
            if slot_state.get("status") in ("filled", "locked"):
                continue
            question = cls.build_question(
                slot_key=key,
                slot_label=slot.get("label"),
                slot_description=slot.get("description"),
                goal_text=goal_text,
                goal_domain=goal_domain,
            )
            return {
                "question": question,
                "target_slot_key": key,
            }
        return None

    @classmethod
    def _resolve_prompt_domain(
        cls,
        *,
        goal_domain: str | None,
        goal_text: str | None,
        slot_key: str,
    ) -> str:
        normalized_domain = (goal_domain or "").strip().lower()
        lowered_goal_text = (goal_text or "").strip().lower()

        if slot_key in {
            "current_fitness_baseline",
            "running_experience",
            "weekly_training_days",
            "daily_session_minutes",
            "injury_constraints",
            "equipment_and_location",
        }:
            return "fitness"
        if slot_key in {
            "current_nutrition_baseline",
            "meal_prep_days_per_week",
            "meals_to_prepare_per_day",
            "protein_goal_grams_per_day",
            "dietary_constraints",
            "prep_time_per_day_minutes",
        }:
            return "nutrition"
        if slot_key in {
            "savings_target",
            "target_date",
            "monthly_income",
            "monthly_fixed_expenses",
            "current_savings",
            "existing_debt",
            "savings_purpose",
        }:
            return "finance"
        if slot_key in {
            "current_skill_level",
            "has_required_equipment",
            "preferred_style_or_genre",
            "daily_practice_minutes",
            "goal_milestone_event",
            "learning_method",
        }:
            return "learning"
        if slot_key in {
            "current_role",
            "target_role",
            "time_in_current_role",
            "target_timeline",
            "manager_feedback_on_gaps",
            "available_opportunities",
        }:
            return "career"

        if normalized_domain == "health":
            nutrition_tokens = ("meal", "nutrition", "protein", "diet", "food", "prep")
            if any(token in lowered_goal_text for token in nutrition_tokens):
                return "nutrition"
            return "fitness"
        if normalized_domain == "financial":
            return "finance"
        if normalized_domain == "learning":
            productivity_tokens = ("focus", "productive", "productivity", "deep work", "organize", "planning")
            if any(token in lowered_goal_text for token in productivity_tokens):
                return "productivity"
            return "learning"
        if normalized_domain in {"career", "personal", "business"}:
            return normalized_domain
        return "personal"
