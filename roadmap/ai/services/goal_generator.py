
# ============================================
# FILE: roadmap/ai/services/generation/goal_generator.py
# Goal Generation Service (Uses Structured Situation)
# ============================================

from typing import Dict, Any, List
from .base_service import BaseAIService
from ai.prompts.system_prompts import SystemPrompts
from ai.prompts.goal_generator import GoalGeneratorPrompts
from ai.prompts.personalization.user_context_prompts import UserContextPrompt
from ai.utils.parsers import ResponseParser
from ai.utils.validators import OutputValidator
from ai.utils.formatters import ResponseFormatter
import logging

logger = logging.getLogger(__name__)


class GoalGenerator(BaseAIService):
    """
    Generate goals, subgoals, and steps from structured user data
    This is the SECOND step - happens after situation analysis
    """
    
    def __init__(self, provider=None):
        super().__init__(provider)
        self.context_prompt = UserContextPrompt()
    
    def generate_roadmap(
        self,
        user_goal_input,
        structured_situation: Dict[str, Any],
        user
    ) -> Dict[str, Any]:
        """
        Generate complete roadmap using structured situation data
        
        Args:
            user_goal_input: UserGoalInput model instance
            structured_situation: Output from SituationGenerator
            user: User model instance
            
        Returns:
            Complete roadmap with goals, subgoals, steps
        """
        # Create processing job
        job = self.create_job(
            user=user,
            job_type='roadmap_generation',
            input_data={
                'user_input_id': str(user_goal_input.id),
                'situation_data': structured_situation
            }
        )
        
        try:
            # Build context-aware prompt
            prompt = self._build_roadmap_prompt(user_goal_input, structured_situation)
            system_prompt = (
                SystemPrompts.get_prompt('goal_generation')
                + "\n\n"
                + GoalGeneratorPrompts.get_roadmap_prompt_template()
            )
            
            # Generate with AI
            logger.info(f"Generating roadmap for user {user.email}")
            response = self.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=4096
            )
            
            # Parse and validate
            parsed_data = ResponseParser.parse_json(response.content)
            goals = ResponseParser.parse_goals(parsed_data)
            
            # Validate
            is_valid, errors = OutputValidator.validate_goals_batch(goals)
            if not is_valid:
                logger.warning(f"Validation warnings: {errors}")
            
            # Format output
            roadmap = {
                'goals': goals,
                'total_goals': len(goals),
                'generation_metadata': {
                    'model': self.provider.model,
                    'tokens_used': response.tokens_used,
                    'latency_ms': response.latency_ms,
                }
            }
            
            # Update job
            self.update_job_success(
                job=job,
                output_data=roadmap,
                tokens_used=response.tokens_used
            )
            
            # Mark user input as processed
            user_goal_input.mark_processed()
            
            return ResponseFormatter.format_success(
                data=roadmap,
                message="Roadmap generated successfully"
            )
            
        except Exception as e:
            logger.error(f"Roadmap generation failed: {str(e)}")
            self.update_job_failure(job, str(e))
            return ResponseFormatter.format_error(str(e), "GENERATION_FAILED")
    
    def _build_roadmap_prompt(
        self,
        user_goal_input,
        structured_situation: Dict[str, Any]
    ) -> str:
        """Build comprehensive roadmap generation prompt"""
        
        # Format user context using structured situation
        user_context = self._format_user_context(user_goal_input, structured_situation)
        
        return f"""
{user_context}

---

# ROADMAP GENERATION TASK

Generate a comprehensive life roadmap that:
1. Aligns with the user's current situation and constraints
2. Addresses their stated goals and aspirations
3. Is realistic given their available time and resources
4. Includes specific, actionable steps

## Requirements:
- Create 4-6 main goals covering different life areas
- Each goal should have 3-5 subgoals
- Each subgoal should have 3-7 actionable steps
- Consider dependencies between goals
- Account for the user's timeline ({user_goal_input.roadmap_duration_years} years)

## Output Format (JSON only):
{{
    "goals": [
        {{
            "title": "Specific, measurable goal",
            "description": "Detailed explanation of what and why",
            "primary_category": "financial|career|health|personal",
            "priority": "high|medium|low",
            "target_date": "YYYY-MM-DD",
            "why_it_matters": "Personal motivation and impact",
            "estimated_duration_days": 180,
            "subgoals": [
                {{
                    "title": "Subgoal title",
                    "description": "What needs to be accomplished",
                    "target_date": "YYYY-MM-DD",
                    "priority": "high|medium|low",
                    "estimated_duration_days": 60,
                    "steps": [
                        {{
                            "title": "Action step",
                            "description": "Brief description",
                            "instructions": "Detailed how-to guide",
                            "estimated_duration_days": 7
                        }}
                    ]
                }}
            ]
        }}
    ]
}}

CRITICAL:
- All dates must be within the {user_goal_input.roadmap_duration_years}-year timeline
- Consider the user's {structured_situation.get('time_availability', 'limited')} time availability
- Respect their {structured_situation.get('financial_status', 'medium')} financial situation
- Match difficulty to their {structured_situation.get('experience_level', 'beginner')} experience level
"""
    
    def _format_user_context(
        self,
        user_goal_input,
        structured_situation: Dict[str, Any]
    ) -> str:
        """Format complete user context"""
        
        # Prepare context variables for UserContextPrompt
        context_vars = {
            'raw_text': structured_situation.get('raw_text', ''),
            'age': structured_situation.get('age', user_goal_input.current_age),
            'current_role': structured_situation.get('current_role', 'Not specified'),
            'profession': structured_situation.get('profession', 'Not specified'),
            'location': structured_situation.get('location', 'Not specified'),
            'life_stage': structured_situation.get('life_stage', 'Not specified'),
            'technical_skills': structured_situation.get('technical_skills', 'None listed'),
            'experience_level': structured_situation.get('experience_level', 'beginner'),
            'other_skills': structured_situation.get('other_skills', 'None listed'),
            'monthly_income': structured_situation.get('monthly_income', 0),
            'currency': structured_situation.get('currency', 'USD'),
            'financial_status': structured_situation.get('financial_status', 'low'),
            'support_system': structured_situation.get('support_system', 'moderate'),
            'time_availability': structured_situation.get('time_availability', 'limited'),
            'financial_constraints': structured_situation.get('financial_constraints', 'Budget conscious'),
            'health_constraints': structured_situation.get('health_constraints', 'None'),
            'other_constraints': structured_situation.get('other_constraints', 'None'),
            'education_goal': structured_situation.get('education_goal', 'Not specified'),
            'career_goal': structured_situation.get('career_goal', 'Not specified'),
            'preferred_country': structured_situation.get('preferred_country', 'Not specified'),
            'data_source': structured_situation.get('data_source', 'user_input'),
            'last_updated': structured_situation.get('last_updated', 'Unknown'),
            'confidence_level': structured_situation.get('confidence_level', 'medium'),
        }
        
        # Format using the UserContextPrompt template
        return self.context_prompt.format(**context_vars)
