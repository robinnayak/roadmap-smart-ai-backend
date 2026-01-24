from ai.services.base_service import BaseAIService
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter
from datetime import timedelta
from ai.prompts.GoalHierarchyGeneratorPrompts import GoalHierarchyGeneratorPrompts


class GoalHierarchyGenerator(BaseAIService):
    """
    Generates complete goal hierarchy from user input.
    
    Flow: Goal → Milestones (Monthly) → SubGoals (Weekly) → Tasks (Daily)
    """

    def __init__(self):
        provider = OllamaProvider(
            model="gpt-oss:120b-cloud", 
            temperature=0.2, 
            max_tokens=4000
        )
        super().__init__(provider)
        self.parser = ResponseParser()
        self.formatter = ResponseFormatter()
        self.prompts = GoalHierarchyGeneratorPrompts()

    def enhance_goal_input(self, goal_inputs, user_context):
        """
        Enhance user's goal description and suggest GoalAttributes.
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_goal_enhancement_prompt(
                    goal_inputs=goal_inputs,
                    user_context=user_context
                ),
                system_prompt="You are a goal enhancement expert."
            )
            
            parsed_data = self.parser.parse_json(response.content)
            return self.formatter.format_success(
                data=parsed_data,
                message="Goal enhanced successfully"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "ENHANCEMENT_FAILED"
            )

    def generate_milestones(self, goal):
        """
        Generate monthly milestones for a goal.
        Example: "ML Interview Prep" → 6 monthly milestones
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_milestone_generating_prompt(goal),
                system_prompt="""You are a milestone planning expert. 
                Create monthly milestones that build progressively."""
            )
            
            parsed_data = self.parser.parse_json(response.content)
            return self.formatter.format_success(
                data=parsed_data,
                message="Milestones generated successfully"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "MILESTONE_GENERATION_FAILED"
            )

    def generate_subgoals(self, milestone):
        """
        Generate weekly subgoals for a milestone.
        Example: Monthly milestone → 4 weekly subgoals
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.subgoal_generating_prompt(milestone),
                system_prompt="""You are a weekly planning expert.
                Break monthly milestones into weekly subgoals."""
            )
            
            parsed_data = self.parser.parse_json(response.content)
            return self.formatter.format_success(
                data=parsed_data,
                message="Subgoals generated successfully"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "SUBGOAL_GENERATION_FAILED"
            )

    def generate_tasks(self, subgoal):
        """
        Generate daily tasks for a weekly subgoal.
        Example: Weekly subgoal → 5 daily tasks (Mon-Fri)
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.task_generating_prompt(subgoal),
                system_prompt="""You are a daily task planner.
                Create specific, actionable daily tasks."""
            )
            
            parsed_data = self.parser.parse_json(response.content)
            return self.formatter.format_success(
                data=parsed_data,
                message="Tasks generated successfully"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "TASK_GENERATION_FAILED"
            )

    def generate_complete_hierarchy(self, user, goal_data):
        """
        Generate complete hierarchy: Goal → Milestones → SubGoals → Tasks
        
        Note: This can be time-consuming. Consider generating in background job.
        """
        try:
            print("=== Starting Hierarchy Generation ===")
            
            # 1. Enhance Goal
            print("1. Enhancing goal...")
            goal_enhanced = self.enhance_goal_input(goal_data, user)
            
            # 2. Generate Milestones (3-6 months)
            print("2. Generating milestones...")
            milestones_result = self.generate_milestones(goal_data)
            milestones = milestones_result.get('data', {}).get('milestones', [])
            print(f"   Created {len(milestones)} milestones")
            
            total_subgoals = 0
            total_tasks = 0
            
            # 3. Generate SubGoals for first 2 milestones (to save time)
            for i, milestone in enumerate(milestones[:2]):
                print(f"3.{i+1}. Generating subgoals for milestone {i+1}...")
                subgoals_result = self.generate_subgoals(milestone)
                subgoals = subgoals_result.get('data', {}).get('subgoals', [])
                total_subgoals += len(subgoals)
                print(f"   Created {len(subgoals)} weekly subgoals")
                
                # 4. Generate Tasks for first week only
                if subgoals:
                    print(f"4.{i+1}. Generating tasks for first week...")
                    tasks_result = self.generate_tasks(subgoals[0])
                    tasks = tasks_result.get('data', {}).get('tasks', [])
                    total_tasks += len(tasks)
                    print(f"   Created {len(tasks)} daily tasks")
            
            return {
                'status': 'success',
                'goal': {
                    'title': goal_data.get('title'),
                    'enhanced': goal_enhanced.get('data')
                },
                'stats': {
                    'milestones_total': len(milestones),
                    'milestones_generated': len(milestones[:2]),
                    'subgoals_generated': total_subgoals,
                    'tasks_generated': total_tasks
                },
                'message': f'Generated {len(milestones[:2])} milestones with subgoals and tasks.'
            }
            
        except Exception as e:
            print(f"Hierarchy generation failed: {str(e)}")
            return {
                'status': 'error',
                'message': f'Failed to generate hierarchy: {str(e)}'
            }

    def validate_hierarchy(self, goal, milestones, subgoals, tasks):
        """
        Validate the complete hierarchy makes sense.
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_hierarchy_validation_prompt(
                    goal, milestones, subgoals, tasks
                ),
                system_prompt="You are a hierarchy validation expert."
            )
            
            parsed_data = self.parser.parse_json(response.content)
            return self.formatter.format_success(
                data=parsed_data,
                message="Hierarchy validated"
            )
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "VALIDATION_FAILED"
            )

    def generate_on_demand(self, parent_obj, level):
        """
        Generate more content on-demand.
        level: 'milestones', 'subgoals', or 'tasks'
        """
        try:
            if level == 'milestones':
                result = self.generate_milestones(parent_obj)
            elif level == 'subgoals':
                result = self.generate_subgoals(parent_obj)
            elif level == 'tasks':
                result = self.generate_tasks(parent_obj)
            else:
                return self.formatter.format_error(
                    "Invalid level", 
                    "INVALID_LEVEL"
                )
            
            return result
            
        except Exception as e:
            return self.formatter.format_error(
                str(e), 
                "ON_DEMAND_GENERATION_FAILED"
            )