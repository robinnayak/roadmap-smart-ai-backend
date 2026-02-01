from ai.services.base_service import BaseAIService
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser, MilestoneParser
from ai.utils.formatters import MileStoneFormatter
from datetime import timedelta
from ai.prompts.GoalHierarchyGeneratorPrompts import GoalHierarchyGeneratorPrompts
import json


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
        self.milestone_parser = MilestoneParser()
        self.parser = ResponseParser()
        self.formatter = MileStoneFormatter()
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
                error_message=str(e),
                error_code="ENHANCEMENT_FAILED"
            )

    def generate_milestones(self, goal):
        """
        Generate monthly milestones for a goal.
        
        Args:
            goal: Can be either:
                - Goal model instance
                - Dictionary with goal data
        
        Returns:
            {
                'status': 'success' | 'error',
                'data': {
                    'milestones': [list of milestone dicts]
                },
                'message': 'Success message'
            }
        """
        try:
            # Calculate months based on target date
            months = 6  # Default
            
            # Determine start and end dates
            if hasattr(goal, 'start_date') and hasattr(goal, 'target_date'):
                # It's a Goal object
                if goal.start_date and goal.target_date:
                    delta = goal.target_date - goal.start_date
                    months = max(3, min(12, delta.days // 30))
            elif isinstance(goal, dict):
                # It's a dictionary
                start_date = goal.get('start_date')
                target_date = goal.get('target_date')
                if start_date and target_date:
                    from datetime import datetime
                    if isinstance(start_date, str):
                        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                    if isinstance(target_date, str):
                        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
                    delta = target_date - start_date
                    months = max(3, min(12, delta.days // 30))
            
            # Generate prompt
            prompt = self.prompts.get_milestone_generating_prompt(goal, months)
            
            system_prompt = """You are an AI planning expert. Break down the goal into monthly milestones.

            Each milestone should:
            - Be achievable in ~30 days
            - Build on previous milestones
            - Have clear success criteria
            - Be specific and measurable

            Respond with valid JSON only."""
            
            # Generate response
            response = self.provider.generate_response(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            print(f"DEBUG: Response type: {type(response)}")
            print(f"DEBUG: Response content type: {type(response.content)}")
            
            # Parse response
            parsed_data = self.milestone_parser.parse_milestones(response.content)
            
            # Ensure we return consistent format
            if isinstance(parsed_data, dict):
                if 'milestones' in parsed_data:
                    milestones_data = parsed_data['milestones']
                else:
                    milestones_data = [parsed_data]
            elif isinstance(parsed_data, list):
                milestones_data = parsed_data
            else:
                milestones_data = []
            
            print(f"DEBUG: Parsed {len(milestones_data)} milestones")
            
            return self.formatter.format_success(
                data={'milestones': milestones_data},
                message=f"Generated {len(milestones_data)} milestones successfully"
            )
            
        except Exception as e:
            print(f"Error generating milestones: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return self.formatter.format_error(
                error_message=str(e),
                error_code="MILESTONE_GENERATION_FAILED"
            )

    def generate_subgoals(self, milestone_data):
        """
        Generate weekly subgoals for a milestone.
        
        Args:
            milestone_data: Dictionary with milestone data or Milestone model instance
        
        Returns:
            {
                'status': 'success' | 'error',
                'data': {
                    'subgoals': [list of subgoal dicts]
                },
                'message': 'Success message'
            }
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_subgoal_generating_prompt(milestone_data),
                system_prompt="""You are a weekly planning expert.
                Break monthly milestones into weekly subgoals.
                
                Respond with valid JSON containing 'subgoals' array."""
            )
            
            parsed_data = self.parser.parse_json(response.content)
            
            # Ensure consistent format
            if isinstance(parsed_data, dict) and 'subgoals' in parsed_data:
                subgoals_data = parsed_data['subgoals']
            elif isinstance(parsed_data, list):
                subgoals_data = parsed_data
            else:
                subgoals_data = []
            
            print(f"DEBUG: Generated {len(subgoals_data)} subgoals")
            
            return self.formatter.format_success(
                data={'subgoals': subgoals_data},
                message=f"Generated {len(subgoals_data)} subgoals successfully"
            )
            
        except Exception as e:
            print(f"Error generating subgoals: {str(e)}")
            return self.formatter.format_error(
                error_message=str(e),
                error_code="SUBGOAL_GENERATION_FAILED"
            )

    def generate_tasks(self, subgoal_data):
        """
        Generate daily tasks for a weekly subgoal.
        
        Args:
            subgoal_data: Dictionary with subgoal data or SubGoal model instance
        
        Returns:
            {
                'status': 'success' | 'error',
                'data': {
                    'tasks': [list of task dicts]
                },
                'message': 'Success message'
            }
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_task_generating_prompt(subgoal_data),
                system_prompt="""You are a daily task planner.
                Create specific, actionable daily tasks.
                
                Respond with valid JSON containing 'tasks' array."""
            )
            
            parsed_data = self.parser.parse_json(response.content)
            
            # Ensure consistent format
            if isinstance(parsed_data, dict) and 'tasks' in parsed_data:
                tasks_data = parsed_data['tasks']
            elif isinstance(parsed_data, list):
                tasks_data = parsed_data
            else:
                tasks_data = []
            
            print(f"DEBUG: Generated {len(tasks_data)} tasks")
            
            return self.formatter.format_success(
                data={'tasks': tasks_data},
                message=f"Generated {len(tasks_data)} tasks successfully"
            )
            
        except Exception as e:
            print(f"Error generating tasks: {str(e)}")
            return self.formatter.format_error(
                error_message=str(e),
                error_code="TASK_GENERATION_FAILED"
            )

    def generate_complete_hierarchy(self, goal_data, user_context=None):
        """
        Generate complete hierarchy: Goal → Milestones → SubGoals → Tasks
        """
        try:
            print("=== Starting Complete Hierarchy Generation ===")
            
            # 1. Generate Milestones
            print("1. Generating milestones...")
            milestones_result = self.generate_milestones(goal_data)
            
            if milestones_result.get('status') != 'success':
                return milestones_result
            
            milestones_list = milestones_result.get('data', {}).get('milestones', [])
            print(f"   Generated {len(milestones_list)} milestones")
            
            all_milestones_data = []
            total_subgoals = 0
            total_tasks = 0
            
            # 2. Generate SubGoals for first 2 milestones (for speed)
            for i, milestone_dict in enumerate(milestones_list[:2]):
                print(f"\n2.{i+1}. Processing milestone: {milestone_dict.get('title', 'Unknown')}")
                
                # Generate subgoals for this milestone
                print(f"   Generating subgoals...")
                subgoals_result = self.generate_subgoals(milestone_dict)
                
                # DEBUG: Print subgoals result
                print(f"   Subgoals result status: {subgoals_result.get('status')}")
                print(f"   Subgoals result data keys: {subgoals_result.get('data', {}).keys() if isinstance(subgoals_result.get('data'), dict) else 'Not a dict'}")
                
                milestone_with_subgoals = {
                    'milestone_data': milestone_dict,
                    'subgoals': []
                }
                
                if subgoals_result.get('status') == 'success':
                    subgoals_list = subgoals_result.get('data', {}).get('subgoals', [])
                    print(f"   Generated {len(subgoals_list)} subgoals")
                    print(f"   Subgoals list: {subgoals_list}")
                    
                    # 3. Generate Tasks for first subgoal only (for speed)
                    if subgoals_list:
                        first_subgoal = subgoals_list[0]
                        print(f"   2.{i+1}.1. Generating tasks for first subgoal: {first_subgoal.get('title', 'Unknown')}")
                        
                        tasks_result = self.generate_tasks(first_subgoal)
                        
                        # DEBUG: Print tasks result
                        print(f"      Tasks result status: {tasks_result.get('status')}")
                        
                        if tasks_result.get('status') == 'success':
                            tasks_list = tasks_result.get('data', {}).get('tasks', [])
                            print(f"      Generated {len(tasks_list)} tasks")
                            print(f"      Tasks list sample: {tasks_list[:2] if tasks_list else 'Empty'}")
                            
                            # Add subgoal with its tasks
                            milestone_with_subgoals['subgoals'].append({
                                'subgoal_data': first_subgoal,
                                'tasks': tasks_list
                            })
                            
                            total_tasks += len(tasks_list)
                    
                    total_subgoals += 1
                
                all_milestones_data.append(milestone_with_subgoals)
            
            print(f"\n=== Generation Complete ===")
            print(f"Final data structure:")
            print(f"  Milestones: {len(all_milestones_data)}")
            for i, milestone in enumerate(all_milestones_data):
                print(f"  Milestone {i+1}: {milestone.get('milestone_data', {}).get('title')}")
                print(f"    Subgoals: {len(milestone.get('subgoals', []))}")
                if milestone.get('subgoals'):
                    for j, subgoal in enumerate(milestone.get('subgoals', [])):
                        print(f"    Subgoal {j+1}: {subgoal.get('subgoal_data', {}).get('title')}")
                        print(f"      Tasks: {len(subgoal.get('tasks', []))}")
            
            return {
                'status': 'success',
                'data': {
                    'milestones': all_milestones_data,
                    'stats': {
                        'milestones_total': len(milestones_list),
                        'milestones_processed': len(all_milestones_data),
                        'subgoals_total': total_subgoals,
                        'tasks_total': total_tasks
                    }
                },
                'message': f'Generated hierarchy with {len(all_milestones_data)} milestones'
            }
            
        except Exception as e:
            print(f"Hierarchy generation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return {
                'status': 'error',
                'message': f'Failed to generate hierarchy: {str(e)}'
            }
        
    def validate_hierarchy(self, goal_data, milestones_data, subgoals_data=None, tasks_data=None):
        """
        Validate the complete hierarchy makes sense.
        """
        try:
            response = self.provider.generate_response(
                prompt=self.prompts.get_hierarchy_validation_prompt(
                    goal_data, milestones_data, subgoals_data, tasks_data
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
                error_message=str(e),
                error_code="VALIDATION_FAILED"
            )

    def generate_on_demand(self, parent_data, level):
        """
        Generate more content on-demand.
        
        Args:
            parent_data: Data of parent item (goal, milestone, or subgoal)
            level: 'milestones', 'subgoals', or 'tasks'
        
        Returns:
            Formatted response with generated data
        """
        try:
            if level == 'milestones':
                result = self.generate_milestones(parent_data)
            elif level == 'subgoals':
                result = self.generate_subgoals(parent_data)
            elif level == 'tasks':
                result = self.generate_tasks(parent_data)
            else:
                return self.formatter.format_error(
                    error_message="Invalid level. Must be 'milestones', 'subgoals', or 'tasks'",
                    error_code="INVALID_LEVEL"
                )
            
            return result
            
        except Exception as e:
            return self.formatter.format_error(
                error_message=str(e),
                error_code="ON_DEMAND_GENERATION_FAILED"
            )

    def generate_milestones_simple(self, goal_data):
        """
        Simplified version that just generates milestones.
        Use this for testing or when you only need milestones.
        """
        try:
            result = self.generate_milestones(goal_data)
            
            if result.get('status') == 'success':
                milestones = result.get('data', {}).get('milestones', [])
                return {
                    'status': 'success',
                    'data': {
                        'milestones': milestones,
                        'count': len(milestones)
                    },
                    'message': f'Generated {len(milestones)} milestones'
                }
            else:
                return result
                
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }