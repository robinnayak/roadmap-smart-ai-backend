from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import AssistantMessageSerializer
from .services import build_assistant_response


class AssistantMessageAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = build_assistant_response(
            request.user,
            serializer.validated_data["message"],
            mode=serializer.validated_data["mode"],
            header_timezone=request.headers.get("X-User-Timezone"),
        )
        return Response(result.as_payload(), status=status.HTTP_200_OK)

