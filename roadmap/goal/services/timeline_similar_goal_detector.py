from __future__ import annotations

from pathlib import Path

from ai.utils.parsers import ResponseParser


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "ai" / "prompts" / "timeline_insight"


def detect_similar_goals(*, current_goal: dict, active_goals: list[dict], provider_adapter) -> list[str]:
    if not active_goals:
        return []

    try:
        prompt = (
            _load_prompt("similar_goal_detector.txt")
            .replace("{current_goal}", _render_goal(current_goal))
            .replace("{active_goals}", _render_goals(active_goals))
        )
        system_prompt = _load_prompt("system.txt")
        response = provider_adapter.generate_timeline_insight(
            prompt=prompt,
            system_prompt=system_prompt,
        )
        parsed = ResponseParser.parse_json(response.content)
        return _validate_findings(parsed)
    except Exception:
        return []


def _validate_findings(payload) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("Detector response must be an object.")

    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Detector findings must be a list.")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in findings:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        deduped.append(cleaned)
        seen.add(cleaned)
        if len(deduped) >= 3:
            break
    return deduped


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _render_goal(goal: dict) -> str:
    return (
        f"- Title: {goal.get('title', '')}\n"
        f"  Description: {goal.get('description', '')}\n"
        f"  Category: {goal.get('primary_category', '')}\n"
        f"  Priority: {goal.get('priority', '')}\n"
        f"  Status: {goal.get('status', '')}\n"
        f"  Target Date: {goal.get('target_date')}\n"
        f"  Progress: {goal.get('progress_percentage', 0)}"
    )


def _render_goals(goals: list[dict]) -> str:
    lines = []
    for goal in goals:
        lines.append(_render_goal(goal))
    return "\n\n".join(lines)
