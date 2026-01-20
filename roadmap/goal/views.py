from django.shortcuts import render
from .serializers import UserCurrentSituationGoalSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserCurrentSituationGoal, Goal, GoalAttributes
from .serializers import GoalSerializer, GoalListSerializer
from django.db.models import Q
from django.utils import timezone
from ai.models import AIProcessingJob
from rest_framework import status
# Create your views here.


class UserCurrentSituationGoalAPIView(APIView):
    permission_classes  = [IsAuthenticated]

    def get_object(self):
        """Get the user's current situation goal object"""
        ai_job = AIProcessingJob.objects.filter(
            user=self.request.user,
            job_type="CURRENT_SITUATION_GENERATION"
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
                status=status.HTTP_404_NOT_FOUND
            )
            
        serializer = UserCurrentSituationGoalSerializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request):
        """Update the user's current situation goal"""
        instance = self.get_object()
        
        if not instance:
            return Response(
                {"detail": "No current situation goal found to update."},
                status=status.HTTP_404_NOT_FOUND
            )
            
        serializer = UserCurrentSituationGoalSerializer(
            instance, 
            data=request.data, 
            partial=True
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
                status=status.HTTP_404_NOT_FOUND
            )
            
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    


# =========== ============
# # Create Goal API View Here GET and POST
# =========== ============

class GoalAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Retrieve all goals for the authenticated user"""
        try:  
            goals = Goal.objects.filter(user=request.user)
            
            # Apply filters
            category = request.query_params.get('category')
            status_filter = request.query_params.get('status')
            priority = request.query_params.get('priority')
            search = request.query_params.get('search')
            overdue = request.query_params.get('overdue')
            if category:
                goals = goals.filter(category=category)
            if status_filter:
                goals = goals.filter(status=status_filter)
            if priority:
                goals = goals.filter(priority=priority)
            if search:
                goals = goals.filter(
                    Q(title__icontains=search) |
                    Q(description__icontains=search) |
                    Q(why_it_matters__icontains=search)
                )
            if overdue == 'true':
                goals = goals.filter(
                    target_date__lt=timezone.now().date(),
                    status__in=['not_started', 'in_progress']
                )
                
            # Apply ordering
            ordering = request.query_params.get('ordering', '-priority,target_date')
            if ordering:
                goals = goals.order_by(*ordering.split(','))
            
            if request.query_params.get('list_view') == 'true':
                serializer = GoalListSerializer(goals, many=True)
            else:
                serializer = GoalSerializer(goals, many=True)
            
            # Use list serializer for list view
            # serializer = GoalListSerializer(goals, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
            
        except Goal.DoesNotExist:
            return Response({"detail": "No goals found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    
    
    def post(self, request):
        """
        POST /api/goals/
        Create a new goal for the authenticated user
        """
        try:
            # Create serializer with request data
            serializer = GoalSerializer(data=request.data)
            
            if serializer.is_valid():
                # Save goal with current user
                goal = serializer.save(user=request.user)
                
                
                
                # Return success response with created goal
                return Response(
                    {
                        "message": "Goal created successfully!",
                        "goal": GoalSerializer(goal).data
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                # Return validation errors
                
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
            

# =========== ============
# # Update Goal API View Here PUT and DELETE
# =========== ============

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
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Convert goal to JSON format
            serializer = GoalSerializer(goal)
            
            # Return the goal data
            return Response(
                {
                    "message": "Goal retrieved successfully",
                    "goal": serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except Goal.DoesNotExist:
            # Goal not found
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            # Any other error
            import traceback 
            traceback.print_exc()
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status=status.HTTP_403_FORBIDDEN
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
                    {
                        "message": "Goal updated successfully",
                        "goal": serializer.data
                    },
                    status=status.HTTP_200_OK
                )
            else:
                # Return validation errors
                return Response(
                    {
                        "message": "Validation failed",
                        "errors": serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Delete the goal
            goal.delete()
            
            return Response(
                {"message": f"Goal '{goal.title}' deleted successfully"},
                status=status.HTTP_200_OK
            )
            
        except Goal.DoesNotExist:
            return Response(
                {"message": f"Goal with ID {goal_id} not found"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            return Response(
                {"message": "Something went wrong", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

