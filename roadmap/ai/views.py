from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

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
            print("Starting current situation generation...")  # Debug
            current_situation_generator = CurrentSituationGenerator()
            
            raw_data = request.data.get('raw_data')
            user_age = request.data.get('user_age')
            
            if not raw_data:
                return Response({"error": "raw_data is required"}, status=400)
            
            print(f"Raw data: {raw_data}")  # Debug
            print(f"User age: {user_age}")  # Debug
            
            user = request.user
            result = current_situation_generator.generate(raw_data, user_age, user)
            print(f"Result: {result}")  # Debug

            return Response(result, status=200)

        except ValueError as ve:
            print(f"ValueError: {str(ve)}")  # Debug
            return Response({"error": str(ve)}, status=400)
        except Exception as e:
            print(f"General error: {str(e)}")  # Debug
            return Response({"error": str(e)}, status=500)
        
class AIHealthCheckView(APIView):
    def get(self, request):
        try:
            print("Running Ollama provider test...")
            
            provider = OllamaProvider(model='llama3.2')
            health_status = provider.health_check()
            
            if health_status["status"] == "healthy":
                return Response({
                    "status": "AI service is healthy",
                    "service": "ollama",
                    "host": health_status.get("host"),
                    "model": health_status.get("model")
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "status": "AI service is unhealthy",
                    "error": health_status.get("error")
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
        except Exception as e:
            return Response({
                "status": "AI service is unhealthy",
                "error": str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
