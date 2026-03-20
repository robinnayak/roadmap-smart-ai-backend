import uuid
from datetime import datetime

from ai.config import get_ollama_model
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from goal.models import Goal
from routine.models import HabitRecommendation
from routine.health_profile_selector import get_effective_profile


def _build_habit_prompt(profile_context: dict, goal: Goal | None) -> str:
    goal_title = goal.title if goal else "General health improvement"
    synthesis_focus = {
        "habits_to_break": profile_context.get("bad_habits", []),
        "health_conditions": profile_context.get("conditions", []),
        "lifestyle": {
            "job_type": profile_context.get("job_type"),
            "job_type_other": profile_context.get("job_type_other"),
            "sleep_pattern": profile_context.get("sleep_pattern"),
            "budget_level": profile_context.get("budget_level"),
        },
        "psychology": {
            "willpower_level": profile_context.get("willpower_level"),
            "stress_level": profile_context.get("stress_level"),
            "motivation_style": profile_context.get("motivation_style"),
        },
    }
    return f"""
User profile context:
{profile_context}

Goal:
{goal_title}

Synthesis requirements:
- Analyze and combine: habits_to_break + health_conditions + lifestyle + psychology
- Suggestions must reflect the user's specific break-habit risks and condition needs
- Keep habits practical for this lifestyle and motivation pattern

Synthesis focus:
{synthesis_focus}

Suggest 4 to 6 habits as JSON only.
Return format:
{{
  "habits": [
    {{
      "name": "string",
      "icon": "string",
      "category": "hydration|movement|nutrition|breathing|mental|sleep|other",
      "estimated_minutes": 15,
      "suggested_time": "HH:MM",
      "frequency": "daily",
      "reason_headline": "string",
      "reason_body": "How To Do It steps as plain text. Prefer numbered steps like '1. ...\\n2. ...\\n3. ...'",
      "science_badge": "string",
      "proof_metric_name": "string",
      "rewards": [
        {{"icon": "string", "label": "string", "sub": "string"}}
      ]
    }}
  ]
}}

Do not suggest habits in existing_habits.
Use free or low-cost habits if budget_level is minimal or low.
Important: `reason_body` must be practical execution steps, not motivational explanation.
Keep steps simple, concrete, and doable in the suggested duration.
""".strip()


def _normalize_ai_habit(raw_habit: dict) -> dict | None:
    name = str(raw_habit.get("name", "")).strip()
    if not name:
        return None

    category = str(raw_habit.get("category", "other")).strip() or "other"
    if category not in {"hydration", "movement", "nutrition", "breathing", "mental", "sleep", "other"}:
        category = "other"

    estimated_minutes = raw_habit.get("estimated_minutes", 30)
    try:
        estimated_minutes = int(estimated_minutes)
    except (TypeError, ValueError):
        estimated_minutes = 30

    suggested_time = None
    raw_time = raw_habit.get("suggested_time")
    if raw_time:
        try:
            suggested_time = datetime.strptime(str(raw_time), "%H:%M").time()
        except ValueError:
            suggested_time = None

    rewards = raw_habit.get("rewards") or []
    if not isinstance(rewards, list):
        rewards = []

    raw_reason_body = raw_habit.get("reason_body")
    if isinstance(raw_reason_body, list):
        reason_body = "\n".join(
            f"{index}. {str(step).strip()}"
            for index, step in enumerate(raw_reason_body, start=1)
            if str(step).strip()
        )
    else:
        reason_body = str(raw_reason_body or "").strip()

    return {
        "name": name,
        "icon": str(raw_habit.get("icon", "⭐"))[:10] or "⭐",
        "category": category,
        "estimated_minutes": max(1, estimated_minutes),
        "suggested_time": suggested_time,
        "frequency": str(raw_habit.get("frequency", "daily"))[:15] or "daily",
        "reason_headline": str(raw_habit.get("reason_headline", ""))[:200],
        "reason_body": reason_body,
        "science_badge": str(raw_habit.get("science_badge", ""))[:100],
        "proof_metric_name": str(raw_habit.get("proof_metric_name", ""))[:100],
        "rewards": rewards,
    }


def generate_habit_recommendations_for_user(
    user,
    goal_id: str | None = None,
    profile_id: str | None = None,
) -> list[HabitRecommendation]:
    try:
        profile = get_effective_profile(user=user, profile_id=profile_id, require_existing=True)
    except Exception as exc:
        raise ValueError(exc.message if hasattr(exc, "message") else str(exc))

    goal = None
    if goal_id:
        goal = Goal.objects.filter(id=goal_id, user=user).first()
        if not goal:
            raise ValueError("Goal not found.")

    profile_context = profile.as_ai_context()
    existing_habits = {str(item).strip().lower() for item in (profile_context.get("existing_habits") or [])}
    pending_recommendation_names = {
        str(name).strip().lower()
        for name in HabitRecommendation.objects.filter(user=user, status="pending").values_list("name", flat=True)
    }

    provider = OllamaProvider(
        model=get_ollama_model(),
        temperature=0.4,
        max_tokens=1200,
    )
    parser = ResponseParser()

    prompt = _build_habit_prompt(profile_context, goal)
    system_prompt = (
        "You are a health habit coach. Output valid JSON only. "
        "Do not include markdown."
    )
    response = provider.generate_response(prompt=prompt, system_prompt=system_prompt)
    parsed = parser.parse_json(response.content)

    raw_habits = parsed.get("habits") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_habits, list):
        raise ValueError("AI returned invalid suggestions format.")

    batch_id = uuid.uuid4()
    recommendations: list[HabitRecommendation] = []
    for raw_habit in raw_habits:
        if not isinstance(raw_habit, dict):
            continue
        normalized = _normalize_ai_habit(raw_habit)
        if not normalized:
            continue
        normalized_name = normalized["name"].strip().lower()
        if normalized_name in existing_habits:
            continue
        if normalized_name in pending_recommendation_names:
            continue
        recommendation = HabitRecommendation.objects.create(
            user=user,
            suggested_for_goal=goal,
            source_health_profile=profile,
            ai_model_used=provider.model,
            generation_batch=batch_id,
            status='pending',
            **normalized,
        )
        recommendations.append(recommendation)
        pending_recommendation_names.add(normalized_name)

    return recommendations
