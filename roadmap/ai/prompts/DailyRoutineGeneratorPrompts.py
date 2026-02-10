from datetime import datetime, timedelta
import json


# ==============================================================================
# PROMPTS FOR DAILY ROUTINE GENERATOR
# ==============================================================================

class DailyRoutineGeneratorPrompts:
    """
    Prompts for AI-powered daily routine generation
    Similar to GoalHierarchyGeneratorPrompts
    """
    
    def get_daily_routine_prompt(self, context):
        """
        Main prompt for generating daily task list
        
        Args:
            context: Dict with user_context, goal_tasks, habits, target_date
        """
        
        user_info = context.get('user_context', {})
        goal_tasks = context.get('goal_tasks', [])
        habits = context.get('habits', [])
        target_date = context.get('target_date', '')
        day_of_week = context.get('day_of_week', '')
        
        prompt = f"""
Generate a personalized daily task list for {day_of_week}, {target_date}.

USER CONTEXT:
{json.dumps(user_info, indent=2)}

AVAILABLE GOAL TASKS ({len(goal_tasks)} tasks):
{json.dumps(goal_tasks, indent=2)}

USER'S HABITS ({len(habits)} habits):
{json.dumps(habits, indent=2)}

YOUR TASK:
Create a balanced, achievable daily task list that:

1. PRIORITIZATION:
   - Select 4-6 most important tasks for today
   - Balance goal tasks with life habits
   - Consider goal priorities and deadlines
   - Don't overwhelm the user

2. PRIORITY ASSIGNMENT:
   - HIGH: Critical goal tasks, important habits
   - MEDIUM: Regular goal tasks, standard habits
   - LOW: Nice-to-have tasks

3. TIME MANAGEMENT:
   - Total daily work should be 4-6 hours
   - Include habits (30-60 min total)
   - Be realistic with time estimates

4. MOTIVATION:
   - Create inspiring daily motivation (2-3 sentences)
   - Create short, powerful daily mantra (5-10 words)

5. WHY IT MATTERS:
   - For each task, explain briefly why it's important today
   - Connect to user's bigger goals

IMPORTANT NOTES:
- Users complete tasks ANYTIME during the day (timing is flexible)
- Focus on WHAT needs to be done, not WHEN
- Suggested times are optional guidance only
- Prioritize by importance, not time of day

RETURN FORMAT (JSON):
{{
  "tasks": [
    {{
      "task_id": "goal_task_id or habit_id",
      "type": "goal_task" or "habit",
      "title": "Task title",
      "description": "Brief description",
      "priority": "high/medium/low",
      "estimated_minutes": 60,
      "why_important": "Why this task matters today",
      "suggested_time_slot": "morning/afternoon/evening (optional)",
      "related_goal": "Goal title (if applicable)"
    }}
  ],
  "motivation": "Personalized daily motivation message",
  "mantra": "Short daily mantra",
  "total_estimated_minutes": 240,
  "focus_area": "Main focus for the day"
}}

Generate the daily routine now:
"""
        return prompt
    
    def get_motivation_prompt(self, user_context, tasks):
        """Generate motivation and mantra"""
        
        prompt = f"""
Create personalized daily motivation for this user.

USER CONTEXT:
{json.dumps(user_context, indent=2)}

TODAY'S TASKS:
{json.dumps(tasks, indent=2)}

Create:
1. MOTIVATION (2-3 sentences):
   - Acknowledge their progress and goals
   - Connect today's tasks to their bigger vision
   - Encourage discipline and consistency
   - Be authentic and inspiring

2. MANTRA (5-10 words):
   - Powerful, actionable statement
   - Easy to remember
   - Connects to their goals
   - Motivates action

RETURN FORMAT (JSON):
{{
  "motivation": "Full motivational message",
  "mantra": "Short powerful mantra"
}}

Generate now:
"""
        return prompt
    
    def get_prioritization_prompt(self, tasks, user_context):
        """Prioritize tasks based on context"""
        
        prompt = f"""
Prioritize these tasks for maximum impact.

USER CONTEXT:
{json.dumps(user_context, indent=2)}

TASKS TO PRIORITIZE:
{json.dumps(tasks, indent=2)}

PRIORITIZATION CRITERIA:
1. Goal importance and priority
2. Deadlines and time sensitivity
3. Impact on overall progress
4. Dependencies (what unlocks other tasks)
5. User's current capacity

ASSIGN PRIORITY:
- HIGH: Must do today, critical impact
- MEDIUM: Should do today, good impact
- LOW: Nice to do today, optional

RETURN FORMAT (JSON):
{{
  "prioritized_tasks": [
    {{
      "task_id": "...",
      "title": "...",
      "priority": "high/medium/low",
      "reasoning": "Why this priority"
    }}
  ]
}}

Prioritize now:
"""
        return prompt
    
    def get_adjustment_prompt(self, incomplete_tasks, user_feedback):
        """Suggest routine adjustments"""
        
        prompt = f"""
User didn't complete all tasks. Help them improve.

INCOMPLETE TASKS:
{json.dumps(incomplete_tasks, indent=2)}

USER FEEDBACK:
{user_feedback}

ANALYZE AND SUGGEST:
1. Why tasks weren't completed
2. How to make routine more realistic
3. What to prioritize tomorrow
4. Strategies to improve completion rate

BE:
- Empathetic but not enabling
- Focus on solutions, not blame
- Encourage accountability
- Provide actionable suggestions

RETURN FORMAT (JSON):
{{
  "analysis": "Why tasks weren't completed",
  "suggestions": [
    "Suggestion 1",
    "Suggestion 2",
    "Suggestion 3"
  ],
  "adjusted_tasks": [
    {{
      "task_id": "...",
      "title": "...",
      "adjustment": "What changed and why",
      "estimated_minutes": 60
    }}
  ],
  "encouragement": "Motivational message"
}}

Generate suggestions now:
"""
        return prompt
    
    def get_habit_suggestion_prompt(self, user_context, current_habits):
        """Suggest new habits based on goals"""
        
        prompt = f"""
Suggest beneficial habits for this user.

USER CONTEXT:
{json.dumps(user_context, indent=2)}

CURRENT HABITS:
{json.dumps(current_habits, indent=2)}

SUGGEST 3-5 NEW HABITS:
- Align with user's goals
- Realistic and achievable
- Fill gaps in current routine
- Evidence-based benefits

RETURN FORMAT (JSON):
{{
  "suggested_habits": [
    {{
      "name": "Habit name",
      "description": "What it involves",
      "why_beneficial": "How it helps user's goals",
      "estimated_minutes": 30,
      "frequency": "daily/weekdays",
      "difficulty": "easy/medium/hard",
      "category": "health/productivity/learning/wellness"
    }}
  ]
}}

Suggest habits now:
"""
        return prompt
    
    def get_weekly_review_prompt(self, week_data):
        """Generate AI insights from weekly performance"""
        
        prompt = f"""
Analyze user's weekly performance and provide insights.

WEEK DATA:
{json.dumps(week_data, indent=2)}

ANALYZE:
1. Overall completion rate and trends
2. Best performing days
3. Common obstacles
4. Progress toward goals
5. Habit consistency

PROVIDE:
1. Key insights (3-5 points)
2. Wins to celebrate
3. Areas to improve
4. Recommendations for next week

RETURN FORMAT (JSON):
{{
  "completion_rate": 75,
  "insights": [
    "Insight 1",
    "Insight 2"
  ],
  "wins": [
    "Win 1",
    "Win 2"
  ],
  "improvement_areas": [
    "Area 1",
    "Area 2"
  ],
  "next_week_recommendations": [
    "Recommendation 1",
    "Recommendation 2"
  ],
  "encouragement": "Motivational message"
}}

Generate review now:
"""
        return prompt