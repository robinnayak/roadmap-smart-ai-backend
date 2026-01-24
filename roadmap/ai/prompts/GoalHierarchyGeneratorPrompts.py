from ai.prompts.base_prompts import BasePrompt


class GoalHierarchyGeneratorPrompts(BasePrompt):

    def get_goal_enhancement_prompt(
        self, goal_inputs, user_context, goal_attributes=None
    ):
        prompt = f"""
Goal: {goal_inputs.title}
Description: {goal_inputs.description}
Category: {goal_inputs.primary_category}
Why: {goal_inputs.why_it_matters}

User Context:
- Age: {user_context.age}
- Role: {user_context.current_role}
- Skills: {user_context.key_skills}
- Time: {user_context.time_availability}

Task: Enhance goal and suggest GoalAttributes based on category.

Rules:
1. Only populate GoalAttributes fields relevant to the goal's category
2. Extract numbers/targets from description
3. Make goal SMART
4. Output JSON only

Output:
{{
  "enhanced_goal": {{"title": "...", "description": "...", "priority": "..."}},
  "goal_attributes": {{"financial_data": {{...}} or null, "career_data": {{...}} or null}},
  "ai_reasoning": "..."
}}
"""
        return prompt

    def get_milestone_generating_prompt(self, goal_context, months):
        prompt = f"""
    Goal: {goal_context.title}
    Description: {goal_context.description}
    Target Date: {goal_context.target_date if hasattr(goal_context, 'target_date') else 'Not set'}
    Categories: {', '.join(goal_context.categories) if goal_context.categories else goal_context.primary_category}
    month: {months}

    
    GoalAttributes to align with:
    Financial: {goal_context.attributes.financial_data if hasattr(goal_context.attributes, 'financial_data') else 'None'}
    Career: {goal_context.attributes.career_data if hasattr(goal_context.attributes, 'career_data') else 'None'}
    Health: {goal_context.attributes.health_data if hasattr(goal_context.attributes, 'health_data') else 'None'}
    Skill: {goal_context.attributes.skill_data if hasattr(goal_context.attributes, 'skill_data') else 'None'}

    Task: Create 3-6 monthly milestones that build progressively.

    For each relevant GoalAttribute field:
    - Extract specific targets (amounts, dates, metrics)
    - Break them down into monthly steps
    - Ensure milestones directly support these targets

    Each milestone should:
    1. Support at least one GoalAttribute target
    2. Be 3-4 weeks of work
    3. Have clear, measurable success criteria
    4. Build on previous milestones

    Output JSON format:
    {{
    "milestones": [
        {{
        "title": "Month 1: [Clear outcome]",
        "description": "What will be accomplished",
        "success_criteria": ["Measurable criteria 1", "Criteria 2"],
        "display_order": 1,
        "priority": "high/medium/low",
        "related_attributes": ["financial_data", "career_data"]  # Which GoalAttributes this supports
        }}
    ],
    "total_months": 4,
    "attributes_coverage": {{
        "financial_data": true/false,
        "career_data": true/false,
        "health_data": true/false,
        "skill_data": true/false
    }}
    }}
    """
        return prompt

    def get_subgoal_generating_prompt(self, milestone_context):
        prompt = f"""
Milestone: {milestone_context['title']}
Description: {milestone_context['description']}
Duration: ~30 days

Task: Create 4 weekly subgoals:
Week 1: Foundation & Setup
Week 2: Core Learning  
Week 3: Application
Week 4: Review & Refinement

Each week should:
1. Have 3-5 learning objectives
2. Build on previous week
3. Be achievable in ~5 days

Output: {{"subgoals": [{{"title": "Week 1: ...", "week_number": 1}}]}}
"""
        return prompt

    def get_task_generating_prompt(self, subgoal_context):
        prompt = f"""
Weekly Subgoal: {subgoal_context['title']}
Objectives: {subgoal_context['learning_objectives']}

Task: Create 5 daily tasks (Monday-Friday):
- Monday: Setup & Planning
- Tue-Thu: Deep Work
- Friday: Review & Wrap-up

Each task should:
1. Be completable in 1-3 hours
2. Have clear success check
3. Include needed resources
4. Use: learning/practice/execution/review types

Output: {{"tasks": [{{"title": "...", "day_order": 1, "estimated_minutes": 120}}]}}
"""
        return prompt

    def get_hierarchy_validation_prompt(self, goal, milestones, subgoals, tasks):
        prompt = f"""
Validate this goal hierarchy:

Goal: {goal['title']}
Milestones: {len(milestones)} months
Subgoals: {len(subgoals)} weeks  
Tasks: {len(tasks)} days

Check:
1. Do tasks support subgoals? Subgoals support milestones?
2. Is workload balanced? Time estimates realistic?
3. Are GoalAttributes targets being addressed?
4. Any missing prerequisites?

Output: {{"is_valid": true/false, "issues": [], "total_hours": number}}
"""
        return prompt
