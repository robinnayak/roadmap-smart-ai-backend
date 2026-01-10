# roadmap\ai\prompts\personalization\user_context_prompts.py

# ============================================
# FILE: roadmap/ai/prompts/personalization/user_context_prompts.py
# User Context & Personalization Prompts
# ============================================

# ============================================
# FILE: roadmap/ai/prompts/personalization/user_context_prompts.py
# User Context & Personalization Prompts
# ============================================

from typing import Dict, Any
from ..base_prompts import BasePrompt


class UserContextPrompt(BasePrompt):
    """
    Builds a context-aware prompt using structured user current_situation data.
    This prompt is designed to work consistently across different user types
    (students, unemployed, employed professionals, career switchers, etc.).
    """

    def __init__(self):
        super().__init__()
        self.age = None
        self.raw_text = None
        self.template = f"Age {self.age}" + f"Row Text {self.raw_text}" + """
# USER CURRENT SITUATION CONTEXT

## Raw Description (User-Provided)
{raw_text}

---

## Profile Snapshot
- Age: {age}
- Current Role: {current_role}
- Profession: {profession}
- Location: {location}
- Life Stage: {life_stage}

---

## Skills & Experience
- Technical Skills: {technical_skills}
- Experience Level: {experience_level}
- Other Skills: {other_skills}

---

## Resources & Support
- Monthly Income: {monthly_income} {currency}
- Financial Status: {financial_status}
- Support System: {support_system}

---

## Constraints
- Time Availability: {time_availability}
- Financial Constraints: {financial_constraints}
- Health Constraints: {health_constraints}
- Other Constraints: {other_constraints}

---

## Aspirations (User-Stated)
- Education Goal: {education_goal}
- Career Goal: {career_goal}
- Preferred Country: {preferred_country}

---

## Metadata
- Data Source: {data_source}
- Last Updated: {last_updated}
- Confidence Level: {confidence_level}

---

### Instructions for Response Generation
Use the above user context strictly as provided.

When generating your response:
1. Respect the user's current role, life stage, and constraints.
2. Align recommendations with available time and financial situation.
3. Match difficulty and pacing to the user's experience level.
4. Avoid assumptions beyond the given data.
5. Keep suggestions realistic, practical, and achievable.
"""
        self.required_variables = [
            # Raw
            "raw_text",
            # Profile snapshot
            "age",
            "current_role",
            "profession",
            "location",
            "life_stage",
            # Skills & experience
            "technical_skills",
            "experience_level",
            "other_skills",
            # Resources
            "monthly_income",
            "currency",
            "financial_status",
            "support_system",
            # Constraints
            "time_availability",
            "financial_constraints",
            "health_constraints",
            "other_constraints",
            # Aspirations
            "education_goal",
            "career_goal",
            "preferred_country",
            # Metadata
            "data_source",
            "last_updated",
            "confidence_level",
        ]

    def get_user_context_prompt_template(self, raw_text, age) -> str:
        """Return the prompt template string."""
        self.raw_text = raw_text
        self.age = age
        return self.template