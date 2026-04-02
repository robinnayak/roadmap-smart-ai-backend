import logging
from pathlib import Path

from ai.prompts.base_prompts import BasePrompt


PROMPTS_DIR = Path(__file__).parent
logger = logging.getLogger(__name__)


class GoalHierarchyGeneratorPrompts(BasePrompt):
    def get_subgoal_generating_prompt(self, milestone_data, goal_data):
        reasons = goal_data.get("why_it_matters", [])
        if isinstance(reasons, list):
            reasons_text = "; ".join([str(item).strip() for item in reasons if str(item).strip()])
        else:
            reasons_text = str(reasons or "").strip()
        prompt = f"""
Goal: {goal_data.get('title', 'Unknown')}
Goal Description: {goal_data.get('description', '')}
Goal Category: {goal_data.get('primary_category', '')}
Goal Priority: {goal_data.get('priority', '')}
Goal Motivation (why_do_i_want_this): {goal_data.get('why_do_i_want_this', '')}
Goal Measurable Target: {goal_data.get('specific_measurable_target', '')}
Goal Reasons (why_it_matters): {reasons_text}
Goal Target Date: {goal_data.get('target_date', '')}
Milestone: {milestone_data.get('title', 'Unknown')}
Description: {milestone_data.get('description', '')}

Create 4 weekly subgoals for this monthly milestone:

Week 1: Foundation & Setup
Week 2: Core Learning
Week 3: Application & Practice
Week 4: Review & Refinement

Each weekly subgoal should:
1. Have 3-5 specific learning objectives
2. Build on the previous week's progress
3. Be achievable in 5-7 days
4. Include clear success criteria
5. Use concrete outcomes, not vague phrases
6. Explicitly connect to the measurable target and stated motivation

Quality requirements:
- Specific and actionable: each subgoal must describe exactly what will be done.
- Proper sequence: Week N must depend on Week N-1 outputs.
- Timeline realism: avoid overloading any week.
- Skill alignment: keep complexity realistic for user context implied by the goal text.

Return ONLY valid JSON (no markdown, no explanation).

IMPORTANT: Return JSON in this EXACT format:
{{
  "subgoals": [
    {{
      "title": "Week 1: [Specific Focus Area]",
      "description": "What will be accomplished this week",
      "learning_objectives": ["Objective 1", "Objective 2", "Objective 3"],
      "week_number": 1,
      "display_order": 1,
      "estimated_duration_days": 7,
      "priority": "high/medium/low",
      "ai_reasoning": "Why this week's focus is important",
      "success_criteria": ["Concrete output 1", "Concrete output 2"]
    }}
  ],
  "quality_check": {{
    "is_specific_and_actionable": true,
    "is_sequenced": true,
    "is_timeline_realistic": true,
    "is_skill_aligned": true,
    "notes": "Short note"
  }}
}}
"""
        return prompt

    def get_task_generating_prompt(self, subgoal_data, milestone_data, goal_data):
        resolved_category = goal_data.get("resolved_category") or goal_data.get("primary_category", "productivity")
        base_rules = _load("shared/base_rules.txt")
        type_schema = _load("shared/task_type_schema.txt")
        system = _load("goal_task/system.txt")
        category = _load_category(resolved_category)
        output_schema = _load("goal_task/output_schema.txt")
        context = _render_context(subgoal_data, milestone_data, goal_data)

        return "\n\n".join(
            [
                base_rules,
                type_schema,
                system,
                category,
                context,
                output_schema,
            ]
        ).strip()

    def get_milestone_generating_prompt(self, goal_context, months):
        prompt = f"""
Goal: {goal_context.get('title', 'Unknown')}
Description: {goal_context.get('description', '')}
Target Date: {goal_context.get('target_date', 'Not set')}
Months to Plan: {months}

Create {max(1, months)} monthly milestones.

Each milestone should:
1. Represent 3-4 weeks of focused work
2. Build on previous milestones
3. Have clear, measurable success criteria
4. Be specific and actionable
5. Fit within the target timeline and avoid overload

Quality requirements:
- Milestone order must be dependency-aware.
- Scope must be realistic per month.
- Must connect clearly to the goal outcome.

Return ONLY valid JSON (no markdown, no explanation).

IMPORTANT: Return JSON in this EXACT format:
{{
  "milestones": [
    {{
      "title": "Month 1: [Clear Outcome]",
      "description": "What will be accomplished this month",
      "success_criteria": ["Criteria 1", "Criteria 2", "Criteria 3"],
      "display_order": 1,
      "priority": "high/medium/low",
      "month_year": "Month 1",
      "estimated_duration_days": 30,
      "ai_reasoning": "Why this milestone comes first"
    }}
  ],
  "quality_check": {{
    "is_specific_and_actionable": true,
    "is_sequenced": true,
    "is_timeline_realistic": true,
    "is_skill_aligned": true,
    "notes": "Short note"
  }}
}}
"""
        return prompt


def _load(relative_path: str) -> str:
    path = PROMPTS_DIR / relative_path
    if not path.exists():
        raise FileNotFoundError(
            f"Required prompt file not found: {path}. "
            "Create it from the architecture document."
        )
    return path.read_text(encoding="utf-8").strip()


def _load_category(category: str) -> str:
    path = PROMPTS_DIR / "categories" / f"{category}.txt"
    if not path.exists():
        logger.warning(
            "No category file for '%s', falling back to 'productivity'",
            category,
        )
        path = PROMPTS_DIR / "categories" / "productivity.txt"
    return path.read_text(encoding="utf-8").strip()


def _render_context(subgoal_data: dict, milestone_data: dict, goal_data: dict) -> str:
    resolved_category = goal_data.get("resolved_category") or goal_data.get("primary_category", "")
    available_daily_minutes = _resolve_available_daily_minutes(goal_data)
    user_strengths = _resolve_user_strengths(goal_data)
    user_blockers = _resolve_user_blockers(goal_data)
    motivation_style = _resolve_motivation_style(goal_data)
    return f"""
USER AND GOAL CONTEXT

GOAL
Title: {goal_data.get('title', '')}
Category: {resolved_category}
Description: {goal_data.get('description', '')}
Why It Matters: {_format_list(goal_data.get('why_it_matters', []))}
Goal Motivation: {goal_data.get('why_do_i_want_this', '')}
Measurable Target: {goal_data.get('specific_measurable_target', '')}
Target Date: {goal_data.get('target_date', '')}

CURRENT MILESTONE
ID: {milestone_data.get('id', '')}
Title: {milestone_data.get('title', '')}
Description: {milestone_data.get('description', '')}
Success Criteria: {_format_list(milestone_data.get('success_criteria', []))}

CURRENT SUBGOAL (generate tasks for this)
Title: {subgoal_data.get('title', '')}
Description: {subgoal_data.get('description', '')}
Week Number: {subgoal_data.get('week_number', '')}
Learning Objectives: {_format_list(subgoal_data.get('learning_objectives', []))}

USER CAPACITY
Available Daily Time: {available_daily_minutes} min
Strengths: {_format_list(user_strengths)}
Blockers: {_format_list(user_blockers)}
Motivation Style: {motivation_style}
""".strip()


def _format_list(items) -> str:
    if isinstance(items, list):
        return ", ".join(str(item) for item in items) if items else "not provided"
    return str(items) if items else "not provided"


def _resolve_available_daily_minutes(goal_data: dict) -> int:
    for key in (
        "available_daily_minutes",
        "daily_session_minutes",
        "daily_practice_minutes",
        "prep_time_per_day_minutes",
    ):
        value = goal_data.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(round(float(value))))
        if isinstance(value, str) and value.strip().isdigit():
            return max(0, int(value.strip()))
    return 60


def _resolve_user_strengths(goal_data: dict) -> list[str]:
    for key in ("user_strengths", "key_skills"):
        value = goal_data.get(key)
        if isinstance(value, list) and value:
            return [str(item).strip() for item in value if str(item).strip()]
    fallback = []
    for key in ("available_opportunities", "running_experience", "current_skill_level", "current_role"):
        value = goal_data.get(key)
        if isinstance(value, str) and value.strip():
            fallback.append(value.strip())
    return fallback


def _resolve_user_blockers(goal_data: dict) -> list[str]:
    for key in ("user_blockers", "constraints"):
        value = goal_data.get(key)
        if isinstance(value, list) and value:
            return [str(item).strip() for item in value if str(item).strip()]
    fallback = []
    for key in ("injury_constraints", "dietary_constraints", "manager_feedback_on_gaps"):
        value = goal_data.get(key)
        if isinstance(value, str) and value.strip():
            fallback.append(value.strip())
    return fallback


def _resolve_motivation_style(goal_data: dict) -> str:
    explicit_style = goal_data.get("motivation_style")
    if isinstance(explicit_style, str) and explicit_style.strip():
        return explicit_style.strip()

    motivation_driver = goal_data.get("motivation_driver")
    if isinstance(motivation_driver, str) and motivation_driver.strip():
        lowered = motivation_driver.strip().lower()
        if any(token in lowered for token in ("deadline", "date", "save", "amount", "race", "event", "target")):
            return "outcome-driven"
        if any(token in lowered for token in ("coach", "mentor", "manager", "accountability")):
            return "accountability-driven"
    return "intrinsic"
