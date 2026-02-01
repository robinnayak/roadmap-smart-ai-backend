from django.shortcuts import render
from .serializers import UserCurrentSituationGoalSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserCurrentSituationGoal, Goal, Milestone, SubGoal, Task
from .serializers import GoalSerializer, GoalListSerializer, MilestoneSerializer, SubGoalSerializer, TaskSerializer
from django.db.models import Q
from django.utils import timezone
from ai.models import AIProcessingJob
from ai.services.text_extraction import GoalAttributeExtractor
from ai.services.GoalHierarchyGenerator import GoalHierarchyGenerator
from rest_framework import status
import json
from authentication.models import UserPersonalDetails


# Create your views here.


class UserCurrentSituationGoalAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self):
        """Get the user's current situation goal object"""
        ai_job = AIProcessingJob.objects.filter(
            user=self.request.user, job_type="CURRENT_SITUATION_GENERATION"
        ).first()

        if not ai_job:
            return None

        return get_object_or_404(UserCurrentSituationGoal, ai_processing_job=ai_job)

    def get(self, request):
        """Retrieve the user's current situation goal"""
        instance = self.get_object()

        if not instance:
            return Response(
                {"detail": "No current situation goal found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserCurrentSituationGoalSerializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        """Update the user's current situation goal"""
        instance = self.get_object()

        if not instance:
            return Response(
                {"detail": "No current situation goal found to update."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserCurrentSituationGoalSerializer(
            instance, data=request.data, partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        """Delete the user's current situation goal"""
        instance = self.get_object()

        if not instance:
            return Response(
                {"detail": "No current situation goal found to delete."},
                status=status.HTTP_404_NOT_FOUND,
            )

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =========== ============
# # Create Goal API View Here GET and POST
# =========== ============

class GoalAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all goals for the authenticated user."""
        print(f"GET Goal API Called")
        try:
            # Use GoalListSerializer for listing (lighter)
            print(f"GET Goal API Called")
            print(f"Request user: {request.user}")
            try: 
                goals = Goal.objects.filter(user=request.user)
                print(f"Goals: {goals}")
            except Goal.DoesNotExist:
                return Response(
                    {"message": "No goals found"},
                    status=status.HTTP_404_NOT_FOUND
                    )
            
            # Check if we want detailed view
            detailed = request.query_params.get('detailed', 'false').lower() == 'true'
            
            if detailed:
                serializer = GoalSerializer(goals, many=True)
            else:
                serializer = GoalListSerializer(goals, many=True)
                
            return Response({
                "count": len(goals),
                "goals": serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {
                    "error": "Failed to fetch goals",
                    "details": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    def post(self, request):
        """
        Create a new goal with optional attribute extraction.
        """
        try:
            print(f"POST Goal API Called")
            print(f"Request data: {request.data}")
            
            data = request.data.copy()
            
            # Add default values if not provided
            if 'start_date' not in data:
                data['start_date'] = timezone.localdate()
                
            if 'progress_percentage' not in data:
                data['progress_percentage'] = 0
            
            # Ensure categories is a list if provided
            if 'categories' in data and isinstance(data['categories'], str):
                try:
                    data['categories'] = json.loads(data['categories'])
                except:
                    # If it's a comma-separated string, convert to list
                    data['categories'] = [cat.strip() for cat in data['categories'].split(',')]
            
            # Create serializer
            serializer = GoalSerializer(
                data=data, 
                context={'request': request}
            )
            
            if serializer.is_valid():
                print(f"Serializer valid, saving goal...")
                # Save goal with current user
                goal = serializer.save(user=request.user)
                
                # Get goal attributes input
                goal_attributes_input = data.get('goal_attributes_input')
                
                # Create response data
                response_data = {
                    "message": "Goal created successfully!",
                    "goal": GoalSerializer(goal).data,
                    "attributes_extracted": bool(goal_attributes_input)
                }
                
                print(f"Goal created: {goal.id}")
                return Response(
                    response_data,
                    status=status.HTTP_201_CREATED
                )
            else:
                print(f"Serializer errors: {serializer.errors}")
                return Response(
                    {
                        "message": "Validation failed",
                        "errors": serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {
                    "message": "Something went wrong",
                    "error": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GoalDetailAPIView(APIView):
    """View to handle single goal operations (GET, PUT, DELETE)"""

    permission_classes = [IsAuthenticated]

    def get(self, request, goal_id):
        """Get a single goal by ID"""
        try:
            # Try to find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check if the goal belongs to the current user
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to view this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Convert goal to JSON format
            serializer = GoalSerializer(goal)

            # Return the goal data
            return Response(
                {"message": "Goal retrieved successfully", "goal": serializer.data},
                status=status.HTTP_200_OK,
            )

        except Goal.DoesNotExist:
            # Goal not found
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            # Any other error
            import traceback

            traceback.print_exc()
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, goal_id):
        """Update a goal completely (all fields must be provided)"""
        try:
            # Find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check ownership
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to update this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Get new data from request
            data = request.data

            # Update the goal with new data
            serializer = GoalSerializer(goal, data=data)

            # Check if data is valid
            if serializer.is_valid():
                # Save the updated goal
                updated_goal = serializer.save()

                return Response(
                    {"message": "Goal updated successfully", "goal": serializer.data},
                    status=status.HTTP_200_OK,
                )
            else:
                # Return validation errors
                return Response(
                    {"message": "Validation failed", "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, goal_id):
        """Delete a goal"""
        try:
            # Find the goal
            goal = Goal.objects.get(id=goal_id)

            # Check ownership
            if goal.user != request.user:
                return Response(
                    {"message": "You don't have permission to delete this goal"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Delete the goal
            goal.delete()

            return Response(
                {"message": f"Goal '{goal.title}' deleted successfully"},
                status=status.HTTP_200_OK,
            )

        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# class CreateGoalWithHierarchyAPIView(APIView):
#     permission_classes = [IsAuthenticated]
    
#     def post(self, request):
#         try:
#             print(f"CREATE GOAL WITH HIERARCHY API Called")
            
#             # 1. Create Goal
#             data = request.data.copy()
#             if 'progress_percentage' not in data:
#                 data['progress_percentage'] = 0
            
#             serializer = GoalSerializer(data=data, context={'request': request})
#             if not serializer.is_valid():
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
#             goal = serializer.save(user=request.user)
#             print(f"✓ Goal created: {goal.id} - {goal.title}")
            
#             # 2. Generate Hierarchy
#             generator = GoalHierarchyGenerator()
            
#             # Prepare goal data
#             goal_data = {
#                 'title': goal.title,
#                 'description': goal.description,
#                 'primary_category': goal.primary_category,
#                 'target_date': goal.target_date,
#                 'start_date': goal.start_date,
#                 'categories': goal.categories,
#                 'why_it_matters': goal.why_it_matters,
#                 'attributes': goal.attributes if hasattr(goal, 'attributes') else None
#             }
            
#             # Generate milestones only (simplified for now)
#             print("Generating milestones...")
#             milestones_result = generator.generate_milestones_simple(goal_data)
            
#             if milestones_result.get('status') != 'success':
#                 return Response({
#                     "message": "Goal created, but failed to generate milestones",
#                     "goal": GoalSerializer(goal).data,
#                     "error": milestones_result.get('message')
#                 }, status=status.HTTP_201_CREATED)
            
#             milestones_data = milestones_result.get('data', {}).get('milestones', [])
            
#             # 3. Save Milestones to Database
#             saved_milestones = self._save_milestones_to_db(goal, milestones_data)
            
#             return Response({
#                 "message": "Goal created successfully with milestones!",
#                 "goal": GoalSerializer(goal).data,
#                 "hierarchy": {
#                     "milestones_generated": len(milestones_data),
#                     "milestones_saved": len(saved_milestones),
#                     "note": "Subgoals and tasks can be generated on-demand"
#                 }
#             }, status=status.HTTP_201_CREATED)
            
#         except Exception as e:
#             print(f"Error: {str(e)}")
#             import traceback
#             traceback.print_exc()
#             return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
#     def _save_milestones_to_db(self, goal, milestones_data):
#         """Save milestones to database and return saved objects"""
#         saved_milestones = []
        
#         for i, milestone_data in enumerate(milestones_data):
#             try:
#                 # Ensure success_criteria is a string
#                 success_criteria = milestone_data.get('success_criteria', [])
#                 if isinstance(success_criteria, list):
#                     success_criteria = json.dumps(success_criteria)
                
#                 milestone = Milestone.objects.create(
#                     goal=goal,
#                     title=milestone_data.get('title', f'Month {i+1}'),
#                     description=milestone_data.get('description', ''),
#                     success_criteria=success_criteria,
#                     display_order=milestone_data.get('display_order', i+1),
#                     priority=milestone_data.get('priority', 'medium'),
#                     month_year=milestone_data.get('month_year', f'Month {i+1}'),
#                     estimated_duration_days=milestone_data.get('estimated_duration_days', 30),
#                     is_ai_generated=True,
#                     ai_reasoning=milestone_data.get('reasoning', 'AI-generated milestone')
#                 )
#                 saved_milestones.append(milestone)
#                 print(f"✓ Saved milestone: {milestone.title}")
#             except Exception as e:
#                 print(f"✗ Error saving milestone {i}: {e}")
        
#         return saved_milestones
        
            
class CreateGoalWithHierarchyAPIView(APIView):
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            print(f"CREATE GOAL WITH HIERARCHY API Called")
            
            # 1. Create Goal
            data = request.data.copy()
            if 'progress_percentage' not in data:
                data['progress_percentage'] = 0
            
            serializer = GoalSerializer(data=data, context={'request': request})
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            goal = serializer.save(user=request.user)
            print(f"✓ Goal created: {goal.id} - {goal.title}")
            
            # 2. Generate Complete Hierarchy
            generator = GoalHierarchyGenerator()
            
            # Prepare goal data
            goal_data = {
                'title': goal.title,
                'description': goal.description,
                'primary_category': goal.primary_category,
                'target_date': goal.target_date,
                'start_date': goal.start_date,
                'categories': goal.categories,
                'why_it_matters': goal.why_it_matters,
                'attributes': goal.attributes if hasattr(goal, 'attributes') else None
            }
            
            # Get user context if available
            user_context = self._get_user_context(request.user)
            
            print("Generating complete hierarchy...")
            hierarchy_result = generator.generate_complete_hierarchy(
                goal_data=goal_data,
                user_context=user_context
            )
            
            if hierarchy_result.get('status') != 'success':
                return Response({
                    "message": "Goal created, but failed to generate complete hierarchy",
                    "goal": GoalSerializer(goal).data,
                    "error": hierarchy_result.get('message')
                }, status=status.HTTP_201_CREATED)
            
            # 3. Save Complete Hierarchy to Database
            saved_counts = self._save_complete_hierarchy_to_db(
                goal, 
                hierarchy_result.get('data', {})
            )
            
            return Response({
                "message": "Goal created successfully with complete hierarchy!",
                "goal": GoalSerializer(goal).data,
                "hierarchy": {
                    "milestones_saved": saved_counts['milestones'],
                    "subgoals_saved": saved_counts['subgoals'],
                    "tasks_saved": saved_counts['tasks'],
                    "total_items": sum(saved_counts.values())
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_user_context(self, user):
        """Get user context for better AI generation"""
        try:
            from authentication.models import UserPersonalDetails
            from ai.models import UserCurrentSituationGoal
            
            user_personal = UserPersonalDetails.objects.get(user=user)
            user_situation = UserCurrentSituationGoal.objects.get(
                user_personal_details=user_personal
            )
            return {
                'age': user_situation.age,
                'current_role': user_situation.current_role,
                'key_skills': user_situation.key_skills,
                'time_availability': user_situation.time_availability
            }
        except Exception as e:
            print(f"Could not get user context: {e}")
            return {}
    
    def _save_complete_hierarchy_to_db(self, goal, hierarchy_data):
        """Save complete hierarchy (milestones + subgoals + tasks) to database"""
        saved_counts = {
            'milestones': 0,
            'subgoals': 0,
            'tasks': 0
        }
        
        milestones_data = hierarchy_data.get('milestones', [])
        print(f"DEBUG: Received {len(milestones_data)} milestones to save")
        
        for i, milestone_entry in enumerate(milestones_data):
            print(f"\nDEBUG: Processing milestone {i+1}")
            milestone_data = milestone_entry.get('milestone_data', {})
            print(f"  Milestone data: {milestone_data.get('title')}")
            
            # Save Milestone
            try:
                milestone = self._save_milestone_to_db(goal, milestone_data, i)
                saved_counts['milestones'] += 1
                
                # Save Subgoals for this milestone
                subgoals_entries = milestone_entry.get('subgoals', [])
                print(f"  Subgoals entries: {len(subgoals_entries)}")
                
                for j, subgoal_entry in enumerate(subgoals_entries):
                    subgoal_data = subgoal_entry.get('subgoal_data', {})
                    tasks_data = subgoal_entry.get('tasks', [])
                    
                    print(f"  Processing subgoal {j+1}: {subgoal_data.get('title', 'Unknown')}")
                    print(f"  Tasks data count: {len(tasks_data)}")
                    
                    # Save SubGoal
                    subgoal = self._save_subgoal_to_db(milestone, subgoal_data, j)
                    saved_counts['subgoals'] += 1
                    
                    # Save Tasks for this subgoal
                    for k, task_data in enumerate(tasks_data):
                        self._save_task_to_db(subgoal, task_data, k)
                        saved_counts['tasks'] += 1
                        
            except Exception as e:
                print(f"✗ Error saving milestone hierarchy {i}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n✓ FINAL SAVED COUNTS: {saved_counts}")
        return saved_counts

    def _save_milestone_to_db(self, goal, milestone_data, index):
        """Save a single milestone to database"""
        success_criteria = milestone_data.get('success_criteria', [])
        if isinstance(success_criteria, list):
            success_criteria = json.dumps(success_criteria)
        
        milestone = Milestone.objects.create(
            goal=goal,
            title=milestone_data.get('title', f'Month {index+1}'),
            description=milestone_data.get('description', ''),
            success_criteria=success_criteria,
            display_order=milestone_data.get('display_order', index+1),
            priority=milestone_data.get('priority', 'medium'),
            month_year=milestone_data.get('month_year', f'Month {index+1}'),
            estimated_duration_days=milestone_data.get('estimated_duration_days', 30),
            is_ai_generated=True,
            ai_reasoning=milestone_data.get('reasoning', milestone_data.get('ai_reasoning', 'AI-generated milestone'))
        )
        print(f"  ✓ Saved milestone: {milestone.title}")
        return milestone
    
    def _save_subgoal_to_db(self, milestone, subgoal_data, index):
        """Save a single subgoal to database"""
        learning_objectives = subgoal_data.get('learning_objectives', [])
        if isinstance(learning_objectives, str):
            try:
                learning_objectives = json.loads(learning_objectives)
            except:
                learning_objectives = [learning_objectives]
        
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title=subgoal_data.get('title', f'Week {index+1}'),
            description=subgoal_data.get('description', ''),
            learning_objectives=learning_objectives,
            week_number=subgoal_data.get('week_number', index+1),
            display_order=subgoal_data.get('display_order', index+1),
            estimated_duration_days=subgoal_data.get('estimated_duration_days', 7),
            priority=subgoal_data.get('priority', 'medium'),
            is_ai_generated=True,
            ai_reasoning=subgoal_data.get('reasoning', subgoal_data.get('ai_reasoning', 'AI-generated subgoal'))
        )
        print(f"    ✓ Saved subgoal: {subgoal.title}")
        return subgoal
    
    def _save_task_to_db(self, subgoal, task_data, index):
        """Save a single task to database"""
        resources = task_data.get('resources', [])
        if isinstance(resources, str):
            try:
                resources = json.loads(resources)
            except:
                resources = [resources]
        
        task = Task.objects.create(
            subgoal=subgoal,
            title=task_data.get('title', f'Task {index+1}'),
            description=task_data.get('description', ''),
            instructions=task_data.get('instructions', ''),
            task_type=task_data.get('task_type', 'learning'),
            resources=resources,
            estimated_duration_minutes=task_data.get('estimated_duration_minutes', 60),
            priority=task_data.get('priority', 'medium'),
            display_order=task_data.get('day_order', index+1),
            is_ai_generated=True,
            ai_reasoning=task_data.get('reasoning', task_data.get('ai_reasoning', 'AI-generated task'))
        )
        print(f"      ✓ Saved task: {task.title}")
        return task
    
    
