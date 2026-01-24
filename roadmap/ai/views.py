from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from goal.models import UserCurrentSituationGoal, GoalAttributes, Goal, Milestone, SubGoal, Task
from authentication.models import UserPersonalDetails
from .models import AIProcessingJob
from ai.services.text_extraction import GoalAttributeExtractor
from ai.services.GoalHierarchyGenerator import GoalHierarchyGenerator
from django.shortcuts import get_object_or_404

# from django.contrib.auth import get_user_model
# User = get_user_model()

# Create your views here.

from .services.current_situation_generator import CurrentSituationGenerator
from .providers.ollama_provider import OllamaProvider


class AIApiView(APIView):
    def get(self, request):
        return Response({"message": "AI endpoint is working!"})


class AIProcessTextDataCurrentSituation(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            current_situation_generator = CurrentSituationGenerator()

            raw_data = request.data.get("raw_data")
            user_age = request.data.get("user_age")

            if not raw_data:
                try:
                    personal_details = UserPersonalDetails.objects.get(
                        user=request.user
                    )
                    raw_data = personal_details.current_situation
                    user_age = personal_details.current_age
                except UserPersonalDetails.DoesNotExist:
                    return Response(
                        {
                            "error": "raw_data is required and no personal details found."
                        },
                        status=400,
                    )

            if not raw_data:
                return Response({"error": "raw_data is required"}, status=400)

            user = request.user
            result = current_situation_generator.generate(raw_data, user_age, user)

            # ✅ Always extract from result payload
            structured_data = result.get("data")
            job_id = result.get("job_id")
            print(f"Structured Data: {structured_data}")  # Debug
            print(f"Job ID: {job_id}")  # Debug

            job = AIProcessingJob.objects.get(id=job_id)
            situation_goal, created = UserCurrentSituationGoal.objects.get_or_create(
                ai_processing_job=job,
                defaults={
                    "current_situation": structured_data,
                    "current_role": structured_data.get("current_role"),
                    "age": structured_data.get("age"),
                    "key_skills": structured_data.get("key_skills"),
                    "main_goals": structured_data.get("main_goals"),
                    "time_availability": structured_data.get("time_availability"),
                    "constraints": structured_data.get("constraints"),
                    "priority_areas": structured_data.get("priority_areas"),
                },
            )
            print(f"Situation & Goals saved for User {user.id}")  # Debug
            print(f"Situation & Goals created: {created}")  # Debug
            print(f"Situation & Goals instance: {situation_goal}")  # Debug

            return Response(result, status=200)

        except ValueError as ve:
            return Response({"error": str(ve)}, status=400)

        except Exception as e:
            return Response(
                {"error": "Internal server error", "details": str(e)}, status=500
            )


class AIHealthCheckView(APIView):
    def get(self, request):
        try:
            print("Running Ollama provider test...")

            provider = OllamaProvider(model="llama3.2")
            health_status = provider.health_check()

            if health_status["status"] == "healthy":
                return Response(
                    {
                        "status": "AI service is healthy",
                        "service": "ollama",
                        "host": health_status.get("host"),
                        "model": health_status.get("model"),
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "status": "AI service is unhealthy",
                        "error": health_status.get("error"),
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        except Exception as e:
            return Response(
                {"status": "AI service is unhealthy", "error": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# Goal Attribute text extraction api view class
class GoalAttributeExtractorAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"message": "Goal Attribute Extraction endpoint is working!"})

    def post(self, request):
        print("creating data...")
        try:
            goal_attribute_extractor = GoalAttributeExtractor()
            user_input = request.data.get("user_input")
            user = request.user
            if not user_input:
                return Response({"error": "user_input is required"}, status=400)
            print("extracting data...")
            result = goal_attribute_extractor.extract_goal_attributes(user_input, user)

            return Response(result, status=200)
        except ValueError as ve:
            return Response({"error": str(ve)}, status=400)
        except KeyError:
            pass
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class GoalEnhancementAPIView(APIView):
    """
    API to enhance a goal and suggest GoalAttributes
    POST: /api/goals/enhance-goal/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            pass
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({"message": "Goal Enhancement endpoint is working!"})

class GenerateMileStonesAPIView(APIView):
    permission_classes =  [IsAuthenticated]
    
    def get(self, request):
        try:
            return Response({"message": "Generate Milestones endpoint is working!"})
        except Exception as e:
            return Response({"message": str(e)}, status= status.HTTP_400_BAD_REQUEST)
    
    def post(self, request, goal_id):
        try:
            if not goal_id:
                return Response({"message": "goal_id is required"}, status= status.HTTP_400_BAD_REQUEST)
            
            goal = get_object_or_404(Goal, id=goal_id, user=request.user)
            if goal.milestones.exists():
                return Response({
                    "message": "Goal already has milestones. Use regenerate endpoint."
                }, status= status.HTTP_202_ACCEPTED)
                    
            generator = GoalHierarchyGenerator()
            result = generator.generate_milestones(goal)
            print("=="*20)
            print(result)
            print("=="*20)
            
            if result.get('status') == 'error':
                return Response(
                    {'error': result.get('message')},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return Response(result, status=status.HTTP_200_OK)

            
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
       

# class GoalEnhancementAPIView(APIView):
#     """
#     API to enhance a goal and suggest GoalAttributes
#     POST: /api/goals/enhance-goal/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         try:
#             goal_data = request.data.get('goal', {})
            
#             # Get user context from UserCurrentSituationGoal
#             from authentication.models import UserPersonalDetails
#             from ai.models import UserCurrentSituationGoal
            
#             user_personal = get_object_or_404(
#                 UserPersonalDetails, 
#                 user=request.user
#             )
            
#             user_context = get_object_or_404(
#                 UserCurrentSituationGoal,
#                 user_personal_details=user_personal
#             )
            
#             # Initialize generator
#             generator = GoalHierarchyGenerator()
            
#             # Enhance goal
#             result = generator.enhance_goal_input(
#                 goal_inputs=goal_data,
#                 user_context={
#                     'age': user_context.age,
#                     'current_role': user_context.current_role,
#                     'key_skills': user_context.key_skills,
#                     'time_availability': user_context.time_availability
#                 }
#             )
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             return Response(result, status=status.HTTP_200_OK)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class GenerateMilestonesAPIView(APIView):
#     """
#     API to generate milestones for a goal
#     POST: /api/goals/{goal_id}/generate-milestones/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, goal_id):
#         try:
#             goal = get_object_or_404(Goal, id=goal_id, user=request.user)
            
#             # Check if goal already has milestones
#             if goal.milestones.exists():
#                 return Response(
#                     {'warning': 'Goal already has milestones. Use regenerate endpoint.'},
#                     status=status.HTTP_200_OK
#                 )
            
#             generator = GoalHierarchyGenerator()
#             result = generator.generate_milestones(goal)
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             # Save milestones to database
#             milestones_data = result.get('data', {}).get('milestones', [])
#             created_milestones = []
            
#             for milestone_data in milestones_data:
#                 milestone = Milestone.objects.create(
#                     goal=goal,
#                     title=milestone_data.get('title'),
#                     description=milestone_data.get('description'),
#                     success_criteria=milestone_data.get('success_criteria'),
#                     month_year=milestone_data.get('month_year', ''),
#                     display_order=milestone_data.get('display_order', 0),
#                     estimated_duration_days=milestone_data.get('estimated_duration_days', 30),
#                     priority=milestone_data.get('priority', 'medium'),
#                     is_ai_generated=True,
#                     ai_reasoning=milestone_data.get('reasoning', '')
#                 )
#                 created_milestones.append(milestone)
            
#             return Response({
#                 'status': 'success',
#                 'message': f'Generated {len(created_milestones)} milestones',
#                 'milestones': MilestoneSerializer(created_milestones, many=True).data
#             }, status=status.HTTP_201_CREATED)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class GenerateSubgoalsAPIView(APIView):
#     """
#     API to generate subgoals for a milestone
#     POST: /api/milestones/{milestone_id}/generate-subgoals/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, milestone_id):
#         try:
#             milestone = get_object_or_404(Milestone, id=milestone_id)
            
#             # Verify ownership
#             if milestone.goal.user != request.user:
#                 return Response(
#                     {'error': 'Permission denied'},
#                     status=status.HTTP_403_FORBIDDEN
#                 )
            
#             # Check if already has subgoals
#             if milestone.subgoals.exists():
#                 return Response(
#                     {'warning': 'Milestone already has subgoals'},
#                     status=status.HTTP_200_OK
#                 )
            
#             generator = GoalHierarchyGenerator()
#             result = generator.generate_subgoals(milestone)
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             # Save subgoals
#             subgoals_data = result.get('data', {}).get('subgoals', [])
#             created_subgoals = []
            
#             for subgoal_data in subgoals_data:
#                 subgoal = SubGoal.objects.create(
#                     milestone=milestone,
#                     title=subgoal_data.get('title'),
#                     description=subgoal_data.get('description'),
#                     learning_objectives=subgoal_data.get('learning_objectives', []),
#                     week_number=subgoal_data.get('week_number'),
#                     display_order=subgoal_data.get('display_order', 0),
#                     estimated_duration_days=subgoal_data.get('estimated_duration_days', 7),
#                     priority=subgoal_data.get('priority', 'medium'),
#                     is_ai_generated=True,
#                     ai_reasoning=subgoal_data.get('reasoning', '')
#                 )
#                 created_subgoals.append(subgoal)
            
#             # Update milestone progress
#             milestone.update_progress()
            
#             return Response({
#                 'status': 'success',
#                 'message': f'Generated {len(created_subgoals)} subgoals',
#                 'subgoals': SubGoalSerializer(created_subgoals, many=True).data
#             }, status=status.HTTP_201_CREATED)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class GenerateTasksAPIView(APIView):
#     """
#     API to generate tasks for a subgoal
#     POST: /api/subgoals/{subgoal_id}/generate-tasks/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, subgoal_id):
#         try:
#             subgoal = get_object_or_404(SubGoal, id=subgoal_id)
            
#             # Verify ownership
#             if subgoal.milestone.goal.user != request.user:
#                 return Response(
#                     {'error': 'Permission denied'},
#                     status=status.HTTP_403_FORBIDDEN
#                 )
            
#             # Check if already has tasks
#             if subgoal.tasks.exists():
#                 return Response(
#                     {'warning': 'Subgoal already has tasks'},
#                     status=status.HTTP_200_OK
#                 )
            
#             generator = GoalHierarchyGenerator()
#             result = generator.generate_tasks(subgoal)
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             # Save tasks
#             tasks_data = result.get('data', {}).get('tasks', [])
#             created_tasks = []
            
#             for task_data in tasks_data:
#                 # Import Task model
#                 from goals.models import Task
                
#                 task = Task.objects.create(
#                     subgoal=subgoal,
#                     title=task_data.get('title'),
#                     description=task_data.get('description'),
#                     instructions=task_data.get('instructions', ''),
#                     task_type=task_data.get('task_type', 'learning'),
#                     resources=task_data.get('resources', []),
#                     estimated_duration_minutes=task_data.get('estimated_duration_minutes', 60),
#                     priority=task_data.get('priority', 'medium'),
#                     is_ai_generated=True,
#                     ai_reasoning=task_data.get('reasoning', '')
#                 )
#                 created_tasks.append(task)
            
#             # Update subgoal progress
#             subgoal.update_progress()
            
#             return Response({
#                 'status': 'success',
#                 'message': f'Generated {len(created_tasks)} tasks',
#                 'tasks': TaskSerializer(created_tasks, many=True).data
#             }, status=status.HTTP_201_CREATED)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class GenerateCompleteHierarchyAPIView(APIView):
#     """
#     API to generate complete hierarchy for a goal
#     POST: /api/goals/{goal_id}/generate-complete-hierarchy/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, goal_id):
#         try:
#             goal = get_object_or_404(Goal, id=goal_id, user=request.user)
            
#             # Check if goal already has content
#             if goal.milestones.exists():
#                 return Response(
#                     {'warning': 'Goal already has content. Use regenerate endpoint.'},
#                     status=status.HTTP_200_OK
#                 )
            
#             # Get user context
#             from authentication.models import UserPersonalDetails
#             from ai.models import UserCurrentSituationGoal
            
#             user_personal = get_object_or_404(
#                 UserPersonalDetails, 
#                 user=request.user
#             )
            
#             user_context = get_object_or_404(
#                 UserCurrentSituationGoal,
#                 user_personal_details=user_personal
#             )
            
#             # Prepare goal data for generator
#             goal_data = {
#                 'title': goal.title,
#                 'description': goal.description,
#                 'primary_category': goal.primary_category,
#                 'target_date': goal.target_date,
#                 'attributes': goal.attributes if hasattr(goal, 'attributes') else None
#             }
            
#             user_context_data = {
#                 'age': user_context.age,
#                 'current_role': user_context.current_role,
#                 'key_skills': user_context.key_skills,
#                 'time_availability': user_context.time_availability
#             }
            
#             generator = GoalHierarchyGenerator()
            
#             # This could be long-running - consider using Celery
#             result = generator.generate_complete_hierarchy(
#                 user=user_context_data,
#                 goal_data=goal_data
#             )
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             return Response(result, status=status.HTTP_201_CREATED)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class ValidateHierarchyAPIView(APIView):
#     """
#     API to validate a goal hierarchy
#     POST: /api/goals/{goal_id}/validate-hierarchy/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, goal_id):
#         try:
#             goal = get_object_or_404(Goal, id=goal_id, user=request.user)
            
#             # Get all related objects
#             milestones = list(goal.milestones.all())
#             subgoals = []
#             tasks = []
            
#             for milestone in milestones:
#                 milestone_subgoals = list(milestone.subgoals.all())
#                 subgoals.extend(milestone_subgoals)
                
#                 for subgoal in milestone_subgoals:
#                     tasks.extend(list(subgoal.tasks.all()))
            
#             # Prepare data for validation
#             goal_data = {
#                 'title': goal.title,
#                 'description': goal.description,
#                 'target_date': goal.target_date
#             }
            
#             milestones_data = [{
#                 'title': m.title,
#                 'description': m.description,
#                 'success_criteria': m.success_criteria
#             } for m in milestones]
            
#             subgoals_data = [{
#                 'title': s.title,
#                 'learning_objectives': s.learning_objectives,
#                 'description': s.description
#             } for s in subgoals]
            
#             tasks_data = [{
#                 'title': t.title,
#                 'estimated_duration_minutes': t.estimated_duration_minutes,
#                 'task_type': t.task_type
#             } for t in tasks]
            
#             generator = GoalHierarchyGenerator()
#             result = generator.validate_hierarchy(
#                 goal=goal_data,
#                 milestones=milestones_data,
#                 subgoals=subgoals_data,
#                 tasks=tasks_data
#             )
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             return Response(result, status=status.HTTP_200_OK)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class GenerateOnDemandAPIView(APIView):
#     """
#     API to generate content on-demand
#     POST: /api/generate-on-demand/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         try:
#             data = request.data
#             parent_id = data.get('parent_id')
#             level = data.get('level')  # 'milestones', 'subgoals', 'tasks'
#             parent_type = data.get('parent_type')  # 'goal', 'milestone', 'subgoal'
            
#             if not all([parent_id, level, parent_type]):
#                 return Response(
#                     {'error': 'Missing required fields'},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             # Get parent object
#             if parent_type == 'goal':
#                 parent_obj = get_object_or_404(Goal, id=parent_id, user=request.user)
#             elif parent_type == 'milestone':
#                 parent_obj = get_object_or_404(Milestone, id=parent_id)
#                 if parent_obj.goal.user != request.user:
#                     return Response(
#                         {'error': 'Permission denied'},
#                         status=status.HTTP_403_FORBIDDEN
#                     )
#             elif parent_type == 'subgoal':
#                 parent_obj = get_object_or_404(SubGoal, id=parent_id)
#                 if parent_obj.milestone.goal.user != request.user:
#                     return Response(
#                         {'error': 'Permission denied'},
#                         status=status.HTTP_403_FORBIDDEN
#                     )
#             else:
#                 return Response(
#                     {'error': 'Invalid parent_type'},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             generator = GoalHierarchyGenerator()
#             result = generator.generate_on_demand(
#                 parent_obj=parent_obj,
#                 level=level
#             )
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             return Response(result, status=status.HTTP_200_OK)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )


# class RegenerateHierarchyAPIView(APIView):
#     """
#     API to regenerate/update existing hierarchy
#     POST: /api/goals/{goal_id}/regenerate-hierarchy/
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, goal_id):
#         try:
#             goal = get_object_or_404(Goal, id=goal_id, user=request.user)
            
#             # Get user feedback/updates
#             feedback = request.data.get('feedback', '')
            
#             # Delete existing AI-generated content
#             goal.milestones.filter(is_ai_generated=True).delete()
            
#             # Regenerate with feedback
#             generator = GoalHierarchyGenerator()
#             result = generator.generate_milestones(goal)
            
#             if result.get('status') == 'error':
#                 return Response(
#                     {'error': result.get('message')},
#                     status=status.HTTP_400_BAD_REQUEST
#                 )
            
#             return Response({
#                 'status': 'success',
#                 'message': 'Hierarchy regenerated successfully',
#                 'data': result.get('data')
#             }, status=status.HTTP_200_OK)
            
#         except Exception as e:
#             return Response(
#                 {'error': str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )   
            


