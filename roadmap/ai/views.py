from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from goal.models import UserCurrentSituationGoal, GoalAttributes
from authentication.models import UserPersonalDetails
from .models import AIProcessingJob
from ai.services.text_extraction import GoalAttributeExtractor

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
