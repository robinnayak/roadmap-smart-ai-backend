
# ============================================
# FILE: roadmap/ai/services/generation/routine_generator.py
# Daily Routine Generation Service
# ============================================

from typing import Dict, Any, List
from .base_service import BaseAIService
from roadmap.ai.prompts.system_prompts import SystemPrompts
from roadmap.ai.utils.parsers import ResponseParser
from roadmap.ai.utils.formatters import ResponseFormatter
import logging

logger = logging.getLogger(__name__)


class RoutineGenerator(BaseAIService):
    """Generate daily routines aligned with goals"""
    
    def generate_routines(
        self,
        goals: List[Dict[str, Any]],
        structured_situation: Dict[str, Any],
        user,
        daily_available_hours: int = 3
    ) -> Dict[str, Any]:
        """
        Generate daily routines that support the user's goals
        
        Args:
            goals: List of goals from GoalGenerator
            structured_situation: User's structured situation
            user: User model instance
            daily_available_hours: Hours available per day
            
        Returns:
            Structured daily routines
        """
        # Create processing job
        job = self.create_job(
            user=user,
            job_type='routine_generation',
            input_data={
                'goals_count': len(goals),
                'daily_hours': daily_available_hours
            }
        )
        
        try:
            # Build prompt
            prompt = self._build_routine_prompt(goals, structured_situation, daily_available_hours)
            system_prompt = SystemPrompts.get_prompt('routine_generation')
            
            # Generate
            logger.info(f"Generating routines for user {user.email}")
            response = self.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.6,
                max_tokens=2048
            )
            
            # Parse
            parsed_data = ResponseParser.parse_json(response.content)
            
            # Format output
            routines = {
                'morning_routines': parsed_data.get('morning', []),
                'afternoon_routines': parsed_data.get('afternoon', []),
                'evening_routines': parsed_data.get('evening', []),
                'total_routines': len(parsed_data.get('morning', [])) + 
                                 len(parsed_data.get('afternoon', [])) + 
                                 len(parsed_data.get('evening', [])),
            }
            
            # Update job
            self.update_job_success(
                job=job,
                output_data=routines,
                tokens_used=response.tokens_used
            )
            
            return ResponseFormatter.format_success(
                data=routines,
                message="Routines generated successfully"
            )
            
        except Exception as e:
            logger.error(f"Routine generation failed: {str(e)}")
            self.update_job_failure(job, str(e))
            return ResponseFormatter.format_error(str(e), "GENERATION_FAILED")
    
    def _build_routine_prompt(
        self,
        goals: List[Dict[str, Any]],
        structured_situation: Dict[str, Any],
        daily_hours: int
    ) -> str:
        """Build routine generation prompt"""
        
        # Extract goal summaries
        goal_summaries = "\n".join([
            f"- {g['title']} ({g['primary_category']})"
            for g in goals[:6]  # Limit to top 6 goals
        ])
        
        return f"""
# DAILY ROUTINE GENERATION TASK

## User Context
- Life Stage: {structured_situation.get('life_stage', 'Not specified')}
- Time Availability: {structured_situation.get('time_availability', 'limited')}
- Daily Available Time: {daily_hours} hours
- Experience Level: {structured_situation.get('experience_level', 'beginner')}

## Goals to Support
{goal_summaries}

---

## Task
Create a daily routine structure that:
1. Supports the user's goals
2. Fits within {daily_hours} hours per day
3. Includes morning, afternoon, and evening activities
4. Is sustainable and realistic
5. Includes both work and rest

## Output Format (JSON only):
{{
    "morning": [
        {{
            "title": "Morning routine activity",
            "description": "What to do",
            "duration_minutes": 30,
            "linked_goal_category": "career|health|personal|financial",
            "instructions": "Step-by-step guide",
            "why_important": "How this supports goals"
        }}
    ],
    "afternoon": [...],
    "evening": [...]
}}

Guidelines:
- Start with 2-3 core routines per time period
- Morning: Focus on energy-building and planning
- Afternoon: Focus on productive work and skill-building  
- Evening: Focus on reflection and preparation for tomorrow
- Keep routines between 15-60 minutes each
"""