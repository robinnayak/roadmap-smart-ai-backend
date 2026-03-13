from copy import deepcopy


WAVE4_DOMAIN_RUNNING_ENDURANCE = "running_endurance"
WAVE4_DOMAIN_FINANCE = "finance"
WAVE4_DOMAIN_SKILL_ACQUISITION = "skill_acquisition"
WAVE4_DOMAIN_CAREER = "career"


def map_session_domain_to_wave4_domain(goal_domain: str | None, goal_text: str = "") -> str:
    normalized_domain = (goal_domain or "").strip().lower()
    if normalized_domain == "career":
        return WAVE4_DOMAIN_CAREER
    if normalized_domain == "financial":
        return WAVE4_DOMAIN_FINANCE
    if normalized_domain == "health":
        return WAVE4_DOMAIN_RUNNING_ENDURANCE
    if normalized_domain == "learning":
        return WAVE4_DOMAIN_SKILL_ACQUISITION

    lowered_goal_text = (goal_text or "").lower()
    if any(token in lowered_goal_text for token in ("save", "saving", "emergency fund", "debt", "income", "expense")):
        return WAVE4_DOMAIN_FINANCE
    if any(token in lowered_goal_text for token in ("run", "running", "marathon", "5k", "10k", "fitness", "endurance")):
        return WAVE4_DOMAIN_RUNNING_ENDURANCE
    if any(token in lowered_goal_text for token in ("learn", "study", "practice", "skill", "language", "guitar", "coding")):
        return WAVE4_DOMAIN_SKILL_ACQUISITION
    return WAVE4_DOMAIN_CAREER


class GIEDynamicSchemaService:
    """Deterministic schema generation with governance-locked required slots."""

    DOMAIN_SCHEMAS = {
        WAVE4_DOMAIN_RUNNING_ENDURANCE: {
            "required_slots": [
                {
                    "key": "current_fitness_baseline",
                    "label": "Current Fitness Baseline",
                    "description": "Current running and endurance baseline.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "running_experience",
                    "label": "Running Experience",
                    "description": "Previous running experience and race history.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "weekly_training_days",
                    "label": "Weekly Training Days",
                    "description": "How many days per week can you train?",
                    "required": True,
                    "data_type": "integer",
                    "enum_values": None,
                    "validation": {"minimum": 1, "maximum": 7},
                },
                {
                    "key": "daily_session_minutes",
                    "label": "Daily Session Minutes",
                    "description": "How many minutes can each session be?",
                    "required": True,
                    "data_type": "integer",
                    "enum_values": None,
                    "validation": {"minimum": 10, "maximum": 300},
                },
                {
                    "key": "injury_constraints",
                    "label": "Injury Constraints",
                    "description": "Current injuries or physical constraints.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {},
                },
                {
                    "key": "equipment_and_location",
                    "label": "Equipment and Location",
                    "description": "Equipment and training environment available.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "motivation_driver",
                    "label": "Motivation Driver",
                    "description": "Primary motivation behind this running goal.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
            ],
            "optional_slots": [
                {
                    "key": "timeline_target_date",
                    "label": "Target Date",
                    "description": "Optional target date for feasibility validation.",
                    "required": False,
                    "data_type": "date",
                    "enum_values": None,
                    "validation": {},
                },
                {
                    "key": "goal_event_type",
                    "label": "Goal Event Type",
                    "description": "Target event type (for example, 5K or half marathon).",
                    "required": False,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {},
                },
            ],
        },
        WAVE4_DOMAIN_FINANCE: {
            "required_slots": [
                {
                    "key": "savings_target",
                    "label": "Savings Target",
                    "description": "Total savings amount to reach.",
                    "required": True,
                    "data_type": "number",
                    "enum_values": None,
                    "validation": {"minimum": 0},
                },
                {
                    "key": "target_date",
                    "label": "Target Date",
                    "description": "By when the savings target should be reached.",
                    "required": True,
                    "data_type": "date",
                    "enum_values": None,
                    "validation": {},
                },
                {
                    "key": "monthly_income",
                    "label": "Monthly Income",
                    "description": "Net monthly income.",
                    "required": True,
                    "data_type": "number",
                    "enum_values": None,
                    "validation": {"minimum": 0},
                },
                {
                    "key": "monthly_fixed_expenses",
                    "label": "Monthly Fixed Expenses",
                    "description": "Monthly fixed obligations and living costs.",
                    "required": True,
                    "data_type": "number",
                    "enum_values": None,
                    "validation": {"minimum": 0},
                },
                {
                    "key": "current_savings",
                    "label": "Current Savings",
                    "description": "Current amount already saved.",
                    "required": True,
                    "data_type": "number",
                    "enum_values": None,
                    "validation": {"minimum": 0},
                },
                {
                    "key": "existing_debt",
                    "label": "Existing Debt",
                    "description": "Monthly debt obligations used for feasibility math.",
                    "required": True,
                    "data_type": "number",
                    "enum_values": None,
                    "validation": {"minimum": 0},
                },
                {
                    "key": "savings_purpose",
                    "label": "Savings Purpose",
                    "description": "Purpose of this savings goal.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
            ],
            "optional_slots": [
                {
                    "key": "risk_tolerance",
                    "label": "Risk Tolerance",
                    "description": "Preferred financial risk posture.",
                    "required": False,
                    "data_type": "enum",
                    "enum_values": ["low", "medium", "high"],
                    "validation": {},
                }
            ],
        },
        WAVE4_DOMAIN_SKILL_ACQUISITION: {
            "required_slots": [
                {
                    "key": "current_skill_level",
                    "label": "Current Skill Level",
                    "description": "Current level in this skill area.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "has_required_equipment",
                    "label": "Has Required Equipment",
                    "description": "Whether required equipment/resources are available.",
                    "required": True,
                    "data_type": "boolean",
                    "enum_values": None,
                    "validation": {},
                },
                {
                    "key": "preferred_style_or_genre",
                    "label": "Preferred Style or Genre",
                    "description": "Preferred style, specialization, or genre.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "daily_practice_minutes",
                    "label": "Daily Practice Minutes",
                    "description": "Daily practice capacity in minutes.",
                    "required": True,
                    "data_type": "integer",
                    "enum_values": None,
                    "validation": {"minimum": 10, "maximum": 360},
                },
                {
                    "key": "goal_milestone_event",
                    "label": "Goal Milestone Event",
                    "description": "Event, output, or checkpoint that marks progress.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "learning_method",
                    "label": "Learning Method",
                    "description": "Primary learning method to follow.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
            ],
            "optional_slots": [
                {
                    "key": "timeline_target_date",
                    "label": "Target Date",
                    "description": "Optional target date for feasibility validation.",
                    "required": False,
                    "data_type": "date",
                    "enum_values": None,
                    "validation": {},
                },
                {
                    "key": "practice_days_per_week",
                    "label": "Practice Days Per Week",
                    "description": "Optional weekly practice-day preference.",
                    "required": False,
                    "data_type": "integer",
                    "enum_values": None,
                    "validation": {"minimum": 1, "maximum": 7},
                },
            ],
        },
        WAVE4_DOMAIN_CAREER: {
            "required_slots": [
                {
                    "key": "current_role",
                    "label": "Current Role",
                    "description": "Current role or position.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "target_role",
                    "label": "Target Role",
                    "description": "Role to move into.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "time_in_current_role",
                    "label": "Time In Current Role",
                    "description": "How long you have been in the current role.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "target_timeline",
                    "label": "Target Timeline",
                    "description": "Desired timeline for the role transition.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "manager_feedback_on_gaps",
                    "label": "Manager Feedback on Gaps",
                    "description": "Known capability gaps based on feedback.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
                {
                    "key": "available_opportunities",
                    "label": "Available Opportunities",
                    "description": "Accessible projects, mentors, or growth opportunities.",
                    "required": True,
                    "data_type": "string",
                    "enum_values": None,
                    "validation": {"min_length": 2},
                },
            ],
            "optional_slots": [
                {
                    "key": "priority",
                    "label": "Priority",
                    "description": "Optional declared priority level.",
                    "required": False,
                    "data_type": "enum",
                    "enum_values": ["low", "medium", "high"],
                    "validation": {},
                }
            ],
        },
    }

    @classmethod
    def generate_schema(cls, goal_text: str, intake_analysis: dict) -> dict:
        session_domain = ((intake_analysis or {}).get("goal_domain") or {}).get("value")
        selected_domain = map_session_domain_to_wave4_domain(session_domain, goal_text)
        schema = deepcopy(cls.DOMAIN_SCHEMAS[selected_domain])
        return {
            "required_slots": schema["required_slots"],
            "optional_slots": schema["optional_slots"],
        }
