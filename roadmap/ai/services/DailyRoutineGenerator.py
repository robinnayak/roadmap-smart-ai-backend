# ==============================================================================
# AI-POWERED DAILY ROUTINE GENERATOR SERVICE
# ==============================================================================
# Similar to GoalHierarchyGenerator but for daily routines
# Uses AI to generate personalized daily task lists
# ==============================================================================

from ai.services.base_service import BaseAIService
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.DailyRoutineFormatterAndParser import DailyRoutineFormatter, DailyRoutineParser
from ai.prompts.DailyRoutineGeneratorPrompts import DailyRoutineGeneratorPrompts







class DailyRoutineGenerator(BaseAIService):
    """
    AI-powered daily routine generator
    
    Similar to GoalHierarchyGenerator but focuses on:
    - Daily task list generation
    - Combining life habits with goal tasks
    - Prioritization based on goals and deadlines
    """
    
    def __init__(self):
        provider = OllamaProvider(
            model="gpt-oss:120b-cloud",
            temperature=0.3,  # Slightly higher for variety
            max_tokens=3000
        )
        super().__init__(provider)
        self.parser = DailyRoutineParser()
        self.formatter = DailyRoutineFormatter()
        self.prompts = DailyRoutineGeneratorPrompts()
    
    def generate_daily_task_list(self, user_context, goal_tasks, habits, target_date):
        """
        Generate complete daily task list using AI
        
        Args:
            user_context: User's situation, preferences, and constraints
            goal_tasks: Available tasks from user's active goals
            habits: User's active habits
            target_date: Date to generate routine for
        
        Returns:
            {
                'status': 'success',
                'data': {
                    'tasks': [list of task dicts],
                    'motivation': 'Daily motivation',
                    'mantra': 'Daily mantra',
                    'total_estimated_minutes': 240
                }
            }
        """
        try:
            print(f"\n{'='*80}")
            print(f"AI GENERATING DAILY ROUTINE FOR {target_date}")
            print(f"{'='*80}\n")
            
            # Prepare context
            context = {
                'user_context': user_context,
                'goal_tasks': self._format_goal_tasks(goal_tasks),
                'habits': self._format_habits(habits),
                'target_date': str(target_date),
                'day_of_week': target_date.strftime('%A')
            }
            
            # Generate routine using AI
            prompt = self.prompts.get_daily_routine_prompt(context)
            
            system_prompt = """You are an expert daily routine planner and productivity coach.
            
            Your task is to create a balanced, achievable daily task list that:
            1. Prioritizes high-impact goal tasks
            2. Includes essential life habits
            3. Respects user's time constraints
            4. Encourages discipline and consistency
            5. Provides motivation and focus
            
            Remember: Timing suggestions are guidance only. Users complete tasks anytime during the day.
            What matters is COMPLETION, not strict timing.
            
            Return valid JSON only."""
            
            print("Sending request to AI...")
            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            print("Parsing AI response...")
            parsed_data = self.parser.parse_response(response.content)
            
            print(f"✓ Generated {len(parsed_data.get('tasks', []))} tasks")
            
            return self.formatter.format_success(
                data=parsed_data,
                message="Daily routine generated successfully"
            )
            
        except Exception as e:
            print(f"❌ Error generating routine: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return self.formatter.format_error(
                error_message=str(e),
                error_code="ROUTINE_GENERATION_FAILED"
            )
    
    def generate_motivation_and_mantra(self, user_context, tasks):
        """
        Generate daily motivation and mantra based on user's goals and tasks
        
        Args:
            user_context: User info and current situation
            tasks: Tasks for the day
        
        Returns:
            {
                'status': 'success',
                'data': {
                    'motivation': 'Long motivational message',
                    'mantra': 'Short daily mantra'
                }
            }
        """
        try:
            prompt = self.prompts.get_motivation_prompt(user_context, tasks)
            
            system_prompt = """You are a motivational coach and mentor.
            Create inspiring, personalized motivation that:
            - Connects to user's specific goals
            - Acknowledges their progress
            - Encourages discipline and consistency
            - Feels personal and authentic
            
            Return valid JSON with 'motivation' and 'mantra' fields."""
            
            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            parsed_data = self.parser.parse_response(response.content)
            
            return self.formatter.format_success(
                data=parsed_data,
                message="Motivation generated"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                error_message=str(e),
                error_code="MOTIVATION_GENERATION_FAILED"
            )
    
    def prioritize_tasks(self, tasks, user_context):
        """
        Use AI to intelligently prioritize tasks
        
        Args:
            tasks: List of tasks to prioritize
            user_context: User's goals, deadlines, preferences
        
        Returns:
            {
                'status': 'success',
                'data': {
                    'prioritized_tasks': [tasks with priority assigned]
                }
            }
        """
        try:
            prompt = self.prompts.get_prioritization_prompt(tasks, user_context)
            
            system_prompt = """You are a task prioritization expert.
            Analyze tasks and assign priorities (high/medium/low) based on:
            - Goal importance and deadlines
            - Impact on overall progress
            - Dependencies and prerequisites
            - User's capacity and constraints
            
            Return valid JSON with prioritized tasks."""
            
            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            parsed_data = self.parser.parse_response(response.content)
            
            return self.formatter.format_success(
                data=parsed_data,
                message="Tasks prioritized"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                error_message=str(e),
                error_code="PRIORITIZATION_FAILED"
            )
    
    def suggest_task_adjustments(self, incomplete_tasks, user_feedback):
        """
        AI suggests how to adjust routine based on incomplete tasks and feedback
        
        Args:
            incomplete_tasks: Tasks user didn't complete
            user_feedback: User's explanation or challenges
        
        Returns:
            {
                'status': 'success',
                'data': {
                    'suggestions': [list of suggestions],
                    'adjusted_tasks': [modified task list]
                }
            }
        """
        try:
            prompt = self.prompts.get_adjustment_prompt(incomplete_tasks, user_feedback)
            
            system_prompt = """You are an adaptive planning assistant.
            Analyze why tasks weren't completed and suggest:
            - More realistic time estimates
            - Better task breakdown
            - Priority adjustments
            - Strategies to overcome obstacles
            
            Be empathetic but encourage accountability.
            Return valid JSON."""
            
            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            parsed_data = self.parser.parse_response(response.content)
            
            return self.formatter.format_success(
                data=parsed_data,
                message="Adjustments suggested"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                error_message=str(e),
                error_code="ADJUSTMENT_FAILED"
            )
    
    def _format_goal_tasks(self, goal_tasks):
        """Format goal tasks for AI prompt"""
        formatted = []
        for task in goal_tasks:
            formatted.append({
                'id': str(task.id),
                'title': task.title,
                'description': task.description,
                'goal_title': task.subgoal.milestone.goal.title,
                'goal_category': task.subgoal.milestone.goal.primary_category,
                'goal_priority': task.subgoal.milestone.goal.priority,
                'estimated_minutes': task.estimated_duration_minutes,
                'task_priority': task.priority if hasattr(task, 'priority') else 'medium',
                'milestone': task.subgoal.milestone.title,
                'subgoal': task.subgoal.title
            })
        return formatted
    
    def _format_habits(self, habits):
        """Format habits for AI prompt"""
        formatted = []
        for habit in habits:
            formatted.append({
                'id': str(habit.id),
                'name': habit.name,
                'description': habit.description,
                'estimated_minutes': habit.estimated_minutes,
                'priority': habit.priority,
                'category': habit.category if hasattr(habit, 'category') else 'wellness',
                'why_important': habit.why_important if hasattr(habit, 'why_important') else ''
            })
        return formatted


