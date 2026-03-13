from copy import deepcopy


class GIEDialogueManagerService:
    """
    Deterministic Step 4 question selection and next-prompt generation.
    """

    SLOT_QUESTION_MAP = {
        "current_role": "What is your current role?",
        "target_role": "What role are you targeting next?",
        "time_in_current_role": "How long have you been in your current role?",
        "target_timeline": "What timeline are you aiming for this transition?",
        "manager_feedback_on_gaps": "What feedback have you received on your current skill gaps?",
        "available_opportunities": "What opportunities do you currently have to grow toward this role?",
        "timeline_target_date": "By what date do you want to achieve this goal?",
        "target_date": "By what date do you want to achieve your savings target?",
        "weekly_training_days": "How many days per week can you train?",
        "daily_session_minutes": "How many minutes can each training session be?",
        "current_fitness_baseline": "What is your current fitness baseline?",
        "running_experience": "What running experience do you already have?",
        "injury_constraints": "Do you have any injury or physical constraints?",
        "equipment_and_location": "What equipment and training location do you have available?",
        "motivation_driver": "What is your main motivation for this goal?",
        "savings_target": "What exact amount do you want to save?",
        "monthly_income": "What is your monthly income?",
        "monthly_fixed_expenses": "What are your monthly fixed expenses?",
        "current_savings": "How much have you already saved?",
        "existing_debt": "What are your monthly debt obligations?",
        "savings_purpose": "What is the purpose of this savings goal?",
        "current_skill_level": "What is your current skill level?",
        "has_required_equipment": "Do you already have the required equipment or tools?",
        "preferred_style_or_genre": "Do you have a preferred style or genre?",
        "daily_practice_minutes": "How many minutes can you practice daily?",
        "goal_milestone_event": "What milestone event will prove meaningful progress?",
        "learning_method": "What learning method do you want to follow?",
    }

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
        next_prompt = cls._select_next_prompt(required_slots, state_by_key)

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
    def _select_next_prompt(cls, required_slots: list, state_by_key: dict) -> dict | None:
        for slot in required_slots:
            key = slot["key"]
            slot_state = state_by_key.get(key, {})
            if slot_state.get("status") in ("filled", "locked"):
                continue
            question = cls.SLOT_QUESTION_MAP.get(key) or f"What is your {slot['label'].lower()}?"
            return {
                "question": question,
                "target_slot_key": key,
            }
        return None
