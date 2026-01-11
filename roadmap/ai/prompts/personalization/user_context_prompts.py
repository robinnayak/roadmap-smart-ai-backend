# roadmap/ai/prompts/personalization/user_context_prompts.py

from ai.prompts.base_prompts import BasePrompt


class UserContextPrompt(BasePrompt):
    """
    Context prompt for extracting and enriching user profile data.
    """

    def __init__(self):
        super().__init__()

        self.template = """
# USER CURRENT SITUATION CONTEXT

## Raw Description
{raw_text}

## Profile
- Age: {age}
- Current Role: {current_role}
- Profession: {profession}
- Location: {location}
- Life Stage: {life_stage}

## Skills & Experience
- Technical Skills: {technical_skills}
- Experience Level: {experience_level}
- Other Skills: {other_skills}

## Resources
- Monthly Income: {monthly_income} {currency}
- Financial Status: {financial_status}
- Support System: {support_system}

## Constraints
- Time Availability: {time_availability}
- Financial Constraints: {financial_constraints}
- Health Constraints: {health_constraints}
- Other Constraints: {other_constraints}

## Aspirations
- Education Goal: {education_goal}
- Career Goal: {career_goal}
- Preferred Country: {preferred_country}

## Metadata
- Source: {data_source}
- Last Updated: {last_updated}
- Confidence: {confidence_level}
"""

        # Only truly mandatory
        self.required_variables = ["raw_text"]

        # Defaults for enrichment
        self.default_variables = {
            "age": None,
            "current_role": None,
            "profession": None,
            "location": None,
            "life_stage": None,
            "technical_skills": [],
            "experience_level": None,
            "other_skills": [],
            "monthly_income": None,
            "currency": None,
            "financial_status": None,
            "non_changeable_job_time": None,
            "support_system": None,
            "time_availability": None,
            "financial_constraints": [],
            "health_constraints": [],
            "other_constraints": [],
            "education_goal": None,
            "career_goal": None,
            "preferred_country": None,
            "data_source": "user_input",
            "last_updated": None,
            "confidence_level": "medium",
        }
