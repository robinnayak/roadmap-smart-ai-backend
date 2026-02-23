from ai.prompts.base_prompts import BasePrompt

class GoalHierarchyGeneratorPrompts(BasePrompt):

    def get_subgoal_generating_prompt(self, milestone_data, goal_data):
        prompt = f"""
Goal: {goal_data.get('title', 'Unknown')}
Goal Description: {goal_data.get('description', '')}
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

    def get_task_generating_prompt(self, subgoal_data, milestone_data):
        prompt = f"""
Weekly Subgoal: {subgoal_data.get('title', 'Unknown')}
Description: {subgoal_data.get('description', '')}
Learning Objectives: {subgoal_data.get('learning_objectives', [])}
Milestone: {milestone_data.get('title', 'Unknown')}

Create 7 daily tasks (Monday-Sunday) for this weekly subgoal:

Daily Structure:
- Monday: Setup, Planning & Foundation
- Tuesday: Deep Work & Learning
- Wednesday: Practice & Application
- Thursday: Implementation & Building
- Friday: Review, Test & Prepare for Next Week

Each daily task should:
1. Be specific and actionable
2. Take 15-180 minutes (avoid unrealistic duration)
3. Have clear instructions
4. Specify task type (learning/practice/project/review/assessment)
5. Include estimated time
6. Include preferred time slot: morning/afternoon/evening
7. Be realistically completable in a single day
8. Maintain progressive difficulty through the week

Quality requirements:
- Avoid vague tasks like "work on it" or "learn more".
- Use action verbs in title (Build/Create/Practice/Review/Analyze/etc).
- Ensure sequence across day_order is logically progressive.
- Include at least one review or assessment task by day 6 or 7.

Return ONLY valid JSON (no markdown, no explanation).

IMPORTANT: Return JSON in this EXACT format:
{{
  "tasks": [
    {{
      "title": "[Verb] [Specific Action]",
      "description": "Detailed description of what to do",
      "instructions": "Step-by-step instructions",
      "task_type": "learning/practice/project/review/assessment",
      "resources": ["Resource 1", "Resource 2"],
      "estimated_duration_minutes": 120,
      "preferred_time_slot": "morning/afternoon/evening",
      "day_order": 1,
      "display_order": 1,
      "priority": "high/medium/low",
      "ai_reasoning": "Why this task is important"
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

    def get_milestone_generating_prompt(self, goal_context, months):
        prompt = f"""
Goal: {goal_context.get('title', 'Unknown')}
Description: {goal_context.get('description', '')}
Target Date: {goal_context.get('target_date', 'Not set')}
Months to Plan: {months}

Create {min(6, max(3, months))} monthly milestones.

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
