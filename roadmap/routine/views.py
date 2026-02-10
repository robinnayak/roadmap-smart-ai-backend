

# ==============================================================================
# API VIEWS FOR DAILY ROUTINE
# ==============================================================================

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta
from ai.services.DailyRoutineGenerator import DailyRoutineGenerator
from goal.models import Task, Goal, UserCurrentSituationGoal
from .models import DailyTaskList, DailyTaskItem, HabitTracker
from .serializers import (
    DailyTaskListSerializer, DailyTaskItemSerializer,
    DailyTaskListSummarySerializer, HabitTrackerSerializer,
    DisciplineStreakSerializer
)
from authentication.models import UserPersonalDetails

            


class GenerateDailyTaskListAPIView(APIView):
    """
    Generate AI-powered daily task list
    
    POST /api/routines/generate/
    Body: {
        "date": "2026-02-05"  # Optional, defaults to today
    }
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            # Get target date
            date_str = request.data.get('date')
            if date_str:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            else:
                target_date = timezone.now().date()
            
            # Check if already exists
            existing = DailyTaskList.objects.filter(
                user=request.user,
                date=target_date
            ).first()
            
            if existing:
                return Response({
                    'message': f'Task list already exists for {target_date}',
                    'task_list': DailyTaskListSerializer(existing).data
                }, status=http_status.HTTP_200_OK)
            
            # Get user context
            user_context = self._get_user_context(request.user)
            
            
            # Get active goals' tasks
            active_goals = Goal.objects.filter(
                user=request.user,
                status__in=['not_started', 'in_progress']
            ).order_by('-priority')
            
            goal_tasks = []
            for goal in active_goals:
                tasks = Task.objects.filter(
                    subgoal__milestone__goal=goal,
                    status='pending'
                ).order_by(
                    'subgoal__milestone__display_order',
                    'subgoal__display_order',
                    'display_order'
                )[:3]  # Top 3 tasks per goal
                goal_tasks.extend(tasks)
            
            # Get active habits
            habits = list(HabitTracker.objects.filter(
                user=request.user,
                is_active=True
            ))
            habits = [h for h in habits if h.should_include_today()]
            
            # Use AI to generate task list
            ai_generator = DailyRoutineGenerator()
            result = ai_generator.generate_daily_task_list(
                user_context=user_context,
                goal_tasks=goal_tasks,
                habits=habits,
                target_date=target_date
            )
            
            if result.get('status') != 'success':
                return Response({
                    'error': 'Failed to generate task list',
                    'details': result.get('message')
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Create DailyTaskList
            ai_data = result.get('data', {})
            task_list = DailyTaskList.objects.create(
                user=request.user,
                date=target_date,
                daily_motivation=ai_data.get('motivation', ''),
                daily_mantra=ai_data.get('mantra', '')
            )
            
            # Create task items
            from .models import DailyTaskItem
            
            for task_data in ai_data.get('tasks', []):
                # Determine if it's a habit or goal task
                task_type = task_data.get('type')
                task_id = task_data.get('task_id')
                
                goal_task = None
                habit = None
                
                if task_type == 'goal_task':
                    try:
                        goal_task = Task.objects.get(id=task_id)
                    except Task.DoesNotExist:
                        continue
                elif task_type == 'habit':
                    try:
                        habit = HabitTracker.objects.get(id=task_id)
                    except HabitTracker.DoesNotExist:
                        continue
                
                DailyTaskItem.objects.create(
                    task_list=task_list,
                    item_type=task_type,
                    goal_task=goal_task,
                    habit=habit,
                    title=task_data.get('title'),
                    description=task_data.get('description', ''),
                    icon=task_data.get('icon', '📌'),
                    priority=task_data.get('priority', 'medium'),
                    estimated_minutes=task_data.get('estimated_minutes', 30),
                    why_important=task_data.get('why_important', ''),
                    related_goal=goal_task.subgoal.milestone.goal if goal_task else (habit.linked_goal if habit else None),
                    display_order=task_data.get('order', 0)
                )
            
            # Update task list stats
            task_list.total_tasks = task_list.tasks.count()
            task_list.save()
            
            return Response({
                'message': 'Daily task list generated successfully',
                'task_list': DailyTaskListSerializer(task_list).data
            }, status=http_status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_user_context(self, user):
        """Get user context for AI"""
        try:
            
            personal = UserPersonalDetails.objects.get(user=user)
            situation = UserCurrentSituationGoal.objects.get(user_personal_details=personal)
            
            return {
                'age': situation.age,
                'current_role': situation.current_role,
                'key_skills': situation.key_skills,
                'main_goals': situation.main_goals,
                'time_availability': situation.time_availability,
                'constraints': situation.constraints
            }
        except:
            return {}


class TodayTaskListAPIView(APIView):
    """
    Get today's task list
    Auto-generates if doesn't exist
    
    GET /api/routines/today/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            today = timezone.now().date()
            
            # Get or create today's task list
            task_list = DailyTaskList.objects.filter(
                user=request.user,
                date=today
            ).first()
            
            if not task_list:
                # Auto-generate using POST to GenerateDailyTaskListAPIView
                generate_view = GenerateDailyTaskListAPIView()
                generate_view.request = request
                response = generate_view.post(request)
                
                if response.status_code == 201:
                    return response
                else:
                    return Response({
                        'error': 'Could not generate task list'
                    }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            return Response({
                'task_list': DailyTaskListSerializer(task_list).data
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class CompleteTaskItemAPIView(APIView):
    """
    Mark task item as completed
    
    POST /api/routines/tasks/<task_id>/complete/
    Body: {
        "notes": "Completed successfully",
        "actual_minutes": 45
    }
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request, task_id):
        try:
            task_item = get_object_or_404(
                DailyTaskItem,
                id=task_id,
                task_list__user=request.user
            )
            
            if task_item.is_completed:
                return Response({
                    'message': 'Task already completed'
                }, status=http_status.HTTP_200_OK)
            
            # Get completion details
            notes = request.data.get('notes', '')
            actual_minutes = request.data.get('actual_minutes')
            
            # Mark as completed
            task_item.mark_completed(
                notes=notes,
                actual_minutes=actual_minutes
            )
            
            # Get updated task list
            task_list = task_item.task_list
            
            return Response({
                'message': 'Task completed successfully',
                'task': DailyTaskItemSerializer(task_item).data,
                'task_list_progress': {
                    'completion_percentage': task_list.completion_percentage,
                    'completed_tasks': task_list.completed_tasks,
                    'total_tasks': task_list.total_tasks,
                    'is_fully_completed': task_list.is_fully_completed
                }
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class SkipTaskItemAPIView(APIView):
    """
    Skip a task item
    
    POST /api/routines/tasks/<task_id>/skip/
    Body: {
        "reason": "No time today"
    }
    """
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request, task_id):
        try:
            task_item = get_object_or_404(
                DailyTaskItem,
                id=task_id,
                task_list__user=request.user
            )
            
            reason = request.data.get('reason', '')
            task_item.mark_skipped(reason=reason)
            
            return Response({
                'message': 'Task skipped',
                'task': DailyTaskItemSerializer(task_item).data
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class WeekOverviewAPIView(APIView):
    """
    Get week overview
    
    GET /api/routines/week/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            today = timezone.now().date()
            start_of_week = today - timedelta(days=today.weekday())
            
            week_data = []
            for day in range(7):
                date = start_of_week + timedelta(days=day)
                
                task_list = DailyTaskList.objects.filter(
                    user=request.user,
                    date=date
                ).first()
                
                if task_list:
                    week_data.append({
                        'date': date.isoformat(),
                        'day_name': date.strftime('%A'),
                        'is_today': date == today,
                        'data': DailyTaskListSummarySerializer(task_list).data
                    })
                else:
                    week_data.append({
                        'date': date.isoformat(),
                        'day_name': date.strftime('%A'),
                        'is_today': date == today,
                        'data': None
                    })
            
            return Response({
                'week_start': start_of_week.isoformat(),
                'days': week_data
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


class DisciplineStreakAPIView(APIView):
    """
    Get user's discipline streak
    
    GET /api/routines/streak/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            from .models import DisciplineStreak
            
            streak, created = DisciplineStreak.objects.get_or_create(
                user=request.user
            )
            
            return Response({
                'streak': DisciplineStreakSerializer(streak).data
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            


class HabitTrackerAPIView(APIView):
    """
    CRUD for habit tracker
    
    GET /api/routines/habits/
    POST /api/routines/habits/
    PUT /api/routines/habits/<habit_id>/
    DELETE /api/routines/habits/<habit_id>/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            habits = HabitTracker.objects.filter(user=request.user)
            return Response({
                'habits': HabitTrackerSerializer(habits, many=True).data
            }, status=http_status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    def post(self, request):
        serializer = HabitTrackerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=http_status.HTTP_201_CREATED)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)
    
    
class HabitDetailAPIView(APIView):
    """
    CRUD for habit tracker detail
    
    GET /api/routines/habits/<habit_id>/
    PUT /api/routines/habits/<habit_id>/
    DELETE /api/routines/habits/<habit_id>/
    """
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request, habit_id):
        try:
            habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
            return Response({
                'habit': HabitTrackerSerializer(habit).data
            }, status=http_status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    def put(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        serializer = HabitTrackerSerializer(habit, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=http_status.HTTP_200_OK)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        habit.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)
    
    