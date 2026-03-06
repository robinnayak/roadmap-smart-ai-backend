from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.ownership import get_owned_object_or_404
from events.models import Event
from events.serializers import EventRangeQuerySerializer, EventSerializer
from events.services import apply_overlap_metadata, expand_event_occurrences


class EventListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Event.objects.filter(user=request.user).order_by("start_at", "created_at")
        serializer = EventSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = EventSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        instance = serializer.save(user=request.user)
        return Response(EventSerializer(instance).data, status=status.HTTP_201_CREATED)


class EventDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, event_id, user):
        return get_owned_object_or_404(Event, user=user, id=event_id)

    def get(self, request, event_id):
        event = self.get_object(event_id=event_id, user=request.user)
        return Response(EventSerializer(event).data, status=status.HTTP_200_OK)

    def patch(self, request, event_id):
        event = self.get_object(event_id=event_id, user=request.user)
        serializer = EventSerializer(event, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, event_id):
        event = self.get_object(event_id=event_id, user=request.user)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EventRangeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = EventRangeQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = query_serializer.validated_data
        start_date = validated["start_date"]
        end_date = validated["end_date"]
        output_timezone = validated.get("timezone")
        include_soft_conflicts = validated.get("include_soft_conflicts", True)

        events = Event.objects.filter(user=request.user).order_by("start_at")
        occurrences = []
        for event in events:
            occurrences.extend(
                expand_event_occurrences(
                    event=event,
                    start_date=start_date,
                    end_date=end_date,
                    output_timezone=output_timezone,
                )
            )

        occurrences.sort(key=lambda item: (item["start_at"], item["end_at"], item["event_id"]))
        occurrences = apply_overlap_metadata(
            occurrences=occurrences,
            include_soft_conflicts=include_soft_conflicts,
        )

        return Response(
            {
                "range": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "timezone": output_timezone or "",
                },
                "occurrences": occurrences,
            },
            status=status.HTTP_200_OK,
        )
