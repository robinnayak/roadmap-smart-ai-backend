from __future__ import annotations

import os
from datetime import date
from typing import Any


class AIGenerator:
    SYSTEM_PROMPT = (
        "You are writing a chapter for a deeply personal memoir about someone's "
        "self-transformation journey. Write with warmth, honesty, and specificity. "
        "Use the data facts provided. Never invent events not supported by the data. "
        "Write 600-900 words as flowing prose paragraphs - no bullet points, no "
        "headers within the chapter text."
    )

    def __init__(self):
        self.provider = None
        try:
            from ai.providers.ollama_provider import OllamaProvider

            self.provider = OllamaProvider(
                host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
                model=os.getenv("JOURNEYBOOK_MODEL", "gpt-oss:20b-cloud"),
                temperature=0.45,
            )
        except Exception:
            self.provider = None

    def generate_chapter(self, chapter_config: dict[str, Any], metrics: dict[str, Any], book_type: str) -> str:
        chapter_id = chapter_config.get("id", "ch1")
        chapter_title = chapter_config.get("title", "Journey Chapter")

        prompt = self._build_chapter_prompt(chapter_id, chapter_title, metrics, book_type)
        text = self._generate_with_ollama(prompt, self.SYSTEM_PROMPT)
        if text:
            return text
        return ChapterFallbacks.get(chapter_id, metrics, book_type)

    def generate_motivational_page(self, page_type: str, metrics: dict[str, Any]) -> str:
        prompt = self._build_motivational_prompt(page_type, metrics)
        system_prompt = (
            "Write a compassionate motivational page for a personal journey book. "
            "Use concrete facts from the provided data. Keep it 300-500 words."
        )
        text = self._generate_with_ollama(prompt, system_prompt)
        if text:
            return text
        return MotivationalFallbacks.get(page_type, metrics)

    def _generate_with_ollama(self, prompt: str, system_prompt: str) -> str | None:
        if not self.provider:
            return None
        try:
            response = self.provider.generate_response(prompt=prompt, system_prompt=system_prompt)
            content = (response.content or "").strip()
            return content or None
        except Exception:
            return None

    @staticmethod
    def _build_chapter_prompt(
        chapter_id: str,
        chapter_title: str,
        metrics: dict[str, Any],
        book_type: str,
    ) -> str:
        flat = ChapterFallbacks._flatten_metrics(metrics)
        return (
            f"Book type: {book_type}\n"
            f"Chapter ID: {chapter_id}\n"
            f"Chapter Title: {chapter_title}\n\n"
            "Facts:\n"
            f"- Name: {flat['name']}\n"
            f"- Goal: {flat['goal_title']}\n"
            f"- Journey start: {flat['start_date']}\n"
            f"- Journey end: {flat['end_date']}\n"
            f"- Total entries: {flat['total_entries']}\n"
            f"- Avg sentiment: {flat['avg_sentiment']}\n"
            f"- Dip period: {flat['dip_start_date']} to {flat['dip_end_date']}\n"
            f"- Comeback date: {flat['comeback_date']}\n"
            f"- Hardest day summary: {flat['hardest_day_summary']}\n"
            f"- Invisible wins summary: {flat['wins_summary']}\n\n"
            "Write the chapter now in prose."
        )

    @staticmethod
    def _build_motivational_prompt(page_type: str, metrics: dict[str, Any]) -> str:
        flat = ChapterFallbacks._flatten_metrics(metrics)
        return (
            f"Page type: {page_type}\n"
            "Use these facts and write a motivating reflection:\n"
            f"- Name: {flat['name']}\n"
            f"- Journey period: {flat['start_date']} to {flat['end_date']}\n"
            f"- Entries written: {flat['total_entries']}\n"
            f"- Longest streak: {flat['longest_streak']}\n"
            f"- Comeback date: {flat['comeback_date']}\n"
            f"- Wins: {flat['wins_summary']}\n"
            f"- Milestones: {flat['milestone_summary']}\n"
        )


class ChapterFallbacks:
    TEMPLATES = {
        "ch1": (
            "On {start_date}, {name} stood at the beginning of a deeply personal "
            "shift. The goal, {goal_title}, was not just a task to complete - it was "
            "a statement about identity. There was uncertainty, and there were old "
            "patterns that had not yet been challenged. But there was also honesty. "
            "The earliest journal pages reveal someone willing to look directly at the "
            "truth of the day, without decoration. That willingness mattered because it "
            "set the tone for everything that followed. This chapter marks the moment "
            "the journey moved from idea into action, with imperfect steps and real "
            "costs that were already visible."
        ),
        "ch2": (
            "The first month of effort was defined by repetition, friction, and small "
            "proof points. {name} kept returning to the work, even when momentum was "
            "fragile. Across {total_entries} entries, the rhythm became clearer: show up, "
            "reflect, adjust, repeat. Some days felt efficient, others felt heavy, but "
            "consistency began to replace hesitation. This period did not look dramatic "
            "from the outside, yet it built the foundation that later chapters depend on."
        ),
        "ch3": (
            "Every serious transformation includes a dip. Between {dip_start_date} and "
            "{dip_end_date}, the journey confronted its hardest stretch. Energy dropped, "
            "confidence narrowed, and the margin for error felt small. The emotional "
            "record from that period explains the cost of growth better than any metric: "
            "discipline without perfect certainty. What matters in hindsight is not that "
            "the dip happened, but that it was survived."
        ),
        "ch4": (
            "The turning point arrived around {comeback_date}. It did not arrive as a "
            "single dramatic event, but as renewed participation after strain. One entry "
            "at a time, {name} rebuilt momentum and recovered trust in the process. "
            "This phase shows what resilience looks like in practice: not avoidance of "
            "difficulty, but return after difficulty."
        ),
        "ch5": (
            "Progress became visible over time. Average sentiment moved to {avg_sentiment}, "
            "and habits that once required force started to feel more natural. The data "
            "is useful, but the deeper change was identity-level: {name} began acting in "
            "alignment with long-term intention more often than not. That is the kind of "
            "change that compounds."
        ),
        "ch6": (
            "Some moments deserve preservation because they carry the emotional truth of "
            "the whole journey. The hardest days, the comeback, and the quiet wins each "
            "added texture to the story. These moments are evidence that growth was not "
            "linear, but it was real. Looking back, the pattern is clear: discomfort was "
            "paid forward into clarity."
        ),
        "ch7": (
            "Who {name} became is shaped by repeated decisions, not single declarations. "
            "From {start_date} to {end_date}, the journey converted intention into lived "
            "evidence. The result is not perfection. The result is a stronger relationship "
            "with commitment, self-honesty, and follow-through. The question was always "
            "what this would cost - and whether it would be worth it. The record now "
            "gives a grounded answer."
        ),
    }

    @classmethod
    def get(cls, chapter_id: str, metrics: dict[str, Any], book_type: str) -> str:
        # AI_UPGRADE_HOOK
        template = cls.TEMPLATES.get(chapter_id, cls.TEMPLATES["ch1"])
        data = cls._flatten_metrics(metrics)
        body = template.format(**data)

        if book_type == "in_progress" and chapter_id in {"ch4", "ch5", "ch6", "ch7"}:
            body = (
                "PROJECTION: The following section is forward-looking based on your "
                "current trajectory.\n\n" + body
            )
        return body

    @classmethod
    def _flatten_metrics(cls, metrics: dict[str, Any]) -> dict[str, Any]:
        overview = metrics.get("journey_overview") or {}
        dip = metrics.get("dip") or {}
        comeback = metrics.get("comeback") or {}
        wins = metrics.get("invisible_wins") or []
        milestones = metrics.get("derived_milestones") or []
        goal = metrics.get("goal") or {}
        profile = metrics.get("profile") or {}

        hardest = metrics.get("hardest_days") or []
        hardest_summary = (
            f"{hardest[0].get('date')}: {hardest[0].get('reflection_snippet', '')[:80]}"
            if hardest
            else "No hardest-day records available."
        )

        wins_summary = ", ".join(win.get("label", "") for win in wins[:4]) or "No wins detected yet."
        milestone_summary = ", ".join(m.get("label", "") for m in milestones[:5]) or "No milestones cached yet."

        return {
            "name": profile.get("name") or profile.get("email") or "the user",
            "goal_title": goal.get("title") or "your journey goal",
            "start_date": cls._date_text(overview.get("start_date")),
            "end_date": cls._date_text(overview.get("end_date")) or cls._date_text(date.today()),
            "total_entries": overview.get("total_entries", 0),
            "avg_sentiment": overview.get("avg_sentiment", 0.0),
            "dip_start_date": cls._date_text(dip.get("dip_start_date")),
            "dip_end_date": cls._date_text(dip.get("dip_end_date")),
            "comeback_date": cls._date_text(comeback.get("comeback_date")),
            "longest_streak": metrics.get("streaks", {}).get("longest_streak", 0),
            "hardest_day_summary": hardest_summary,
            "wins_summary": wins_summary,
            "milestone_summary": milestone_summary,
        }

    @staticmethod
    def _date_text(value: Any) -> str:
        if value is None:
            return "unknown date"
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


class MotivationalFallbacks:
    TEMPLATES = {
        "the_day_you_didnt_quit": (
            "You returned to the page when it would have been easier not to. "
            "That choice carried the story forward."
        ),
        "before_after": (
            "Before this journey, consistency was a hope. After this journey, "
            "consistency became a practiced behavior."
        ),
        "streak_heatmap": (
            "Each marked day is proof that long-term change is built through "
            "ordinary repetition."
        ),
        "invisible_wins": (
            "The biggest wins were often invisible at the time: showing up tired, "
            "resetting after setbacks, and continuing without applause."
        ),
        "what_you_learned": (
            "You learned that confidence follows action. The habit of returning is "
            "more important than perfect daily performance."
        ),
        "three_hardest_days": (
            "The hardest days did not define your limit. They revealed your ability "
            "to continue under pressure."
        ),
        "milestones_map": (
            "Milestones are more than markers - they are receipts for effort paid "
            "in full over time."
        ),
        "letter_to_past_self": (
            "Dear past self: you were right to begin, even before you knew how this "
            "would unfold."
        ),
    }

    @classmethod
    def get(cls, page_type: str, metrics: dict[str, Any]) -> str:
        # AI_UPGRADE_HOOK
        base = cls.TEMPLATES.get(page_type, cls.TEMPLATES["invisible_wins"])
        flat = ChapterFallbacks._flatten_metrics(metrics)
        return (
            f"{base}\n\n"
            f"Journey window: {flat['start_date']} to {flat['end_date']}.\n"
            f"Entries written: {flat['total_entries']}.\n"
            f"Comeback date: {flat['comeback_date']}."
        )
