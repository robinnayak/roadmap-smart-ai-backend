from datetime import datetime

from django.db.models import Count, F, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.models import CustomUser
from community.models import (
    CommunityDiscussion,
    CommunityEvent,
    CommunityLeaderboardEntry,
    CommunityTopic,
)


SEED_DISCUSSIONS = [
    {
        "id": "1",
        "title": "How to stay consistent with morning routine?",
        "content": "I have been struggling to wake up early consistently. Any tips?",
        "category": "routines",
        "author_id": "u1",
        "author_name": "Alex Chen",
        "author_avatar": "https://i.pravatar.cc/150?u=1",
        "author_role": "member",
        "author_level": 12,
        "author_badges": 5,
        "author_reputation": 450,
        "created_at": "2024-02-21T08:30:00Z",
        "likes": 24,
        "comments": 15,
        "views": 342,
        "is_pinned": False,
        "is_hot": True,
        "last_activity": "2024-02-21T14:20:00Z",
        "tags": ["morning-routine", "discipline", "habits"],
    },
    {
        "id": "2",
        "title": "30-Day Productivity Challenge - Join Us!",
        "content": "Starting March 1st, we are doing a 30-day productivity challenge.",
        "category": "motivation",
        "author_id": "u2",
        "author_name": "Sarah Johnson",
        "author_avatar": "https://i.pravatar.cc/150?u=2",
        "author_role": "contributor",
        "author_level": 24,
        "author_badges": 12,
        "author_reputation": 1250,
        "created_at": "2024-02-20T10:15:00Z",
        "likes": 156,
        "comments": 67,
        "views": 1234,
        "is_pinned": True,
        "is_hot": True,
        "last_activity": "2024-02-21T15:45:00Z",
        "tags": ["challenge", "productivity", "community"],
    },
    {
        "id": "3",
        "title": "How do you track your habits effectively?",
        "content": "Looking for recommendations on habit tracking methods that work.",
        "category": "habits",
        "author_id": "u3",
        "author_name": "Emily Zhang",
        "author_avatar": "https://i.pravatar.cc/150?u=3",
        "author_role": "member",
        "author_level": 15,
        "author_badges": 7,
        "author_reputation": 680,
        "created_at": "2024-02-20T16:20:00Z",
        "likes": 34,
        "comments": 28,
        "views": 456,
        "is_pinned": False,
        "is_hot": False,
        "last_activity": "2024-02-21T11:30:00Z",
        "tags": ["habits", "tracking", "tools"],
    },
]

SEED_TOPICS = [
    {"id": "t1", "name": "Morning Routines", "category": "routines", "count": 234, "trend": "up"},
    {"id": "t2", "name": "Goal Setting", "category": "goals", "count": 567, "trend": "up"},
    {"id": "t3", "name": "Habit Formation", "category": "habits", "count": 345, "trend": "up"},
]

SEED_EVENTS = [
    {
        "id": "e1",
        "title": "Weekly Community Meetup",
        "description": "Virtual coffee chat to connect with fellow goal-crushers",
        "event_type": "meetup",
        "start_date": "2024-02-23T15:00:00Z",
        "end_date": "2024-02-23T16:30:00Z",
        "attendees": 89,
        "host_id": "u5",
        "host_name": "David Kim",
        "host_avatar": "https://i.pravatar.cc/150?u=5",
        "host_role": "moderator",
        "host_level": 32,
        "host_badges": 18,
        "host_reputation": 2450,
    }
]

SEED_LEADERBOARD = [
    {
        "id": "u5",
        "name": "David Kim",
        "avatar": "https://i.pravatar.cc/150?u=5",
        "level": 32,
        "points": 2450,
        "streak": 45,
        "rank": 1,
        "change": "up",
    },
    {
        "id": "u2",
        "name": "Sarah Johnson",
        "avatar": "https://i.pravatar.cc/150?u=2",
        "level": 24,
        "points": 1250,
        "streak": 23,
        "rank": 2,
        "change": "same",
    },
]


def _parse_utc_timestamp(raw_value: str):
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))


def _ensure_seed_data():
    """
    Ensure community endpoints are storage-backed while still returning a useful
    payload in empty/local environments.
    """
    if not CommunityDiscussion.objects.exists():
        for payload in SEED_DISCUSSIONS:
            CommunityDiscussion.objects.update_or_create(
                id=payload["id"],
                defaults={
                    **payload,
                    "created_at": _parse_utc_timestamp(payload["created_at"]),
                    "last_activity": _parse_utc_timestamp(payload["last_activity"]),
                },
            )

    if not CommunityTopic.objects.exists():
        for payload in SEED_TOPICS:
            CommunityTopic.objects.update_or_create(
                id=payload["id"],
                defaults={
                    **payload,
                    "created_at": timezone.now(),
                },
            )

    if not CommunityEvent.objects.exists():
        for payload in SEED_EVENTS:
            CommunityEvent.objects.update_or_create(
                id=payload["id"],
                defaults={
                    **payload,
                    "start_date": _parse_utc_timestamp(payload["start_date"]),
                    "end_date": _parse_utc_timestamp(payload["end_date"]),
                    "created_at": timezone.now(),
                },
            )

    if not CommunityLeaderboardEntry.objects.exists():
        for payload in SEED_LEADERBOARD:
            CommunityLeaderboardEntry.objects.update_or_create(
                id=payload["id"],
                defaults={
                    **payload,
                    "created_at": timezone.now(),
                },
            )


def _serialize_discussion(discussion: CommunityDiscussion) -> dict:
    return {
        "id": discussion.id,
        "title": discussion.title,
        "content": discussion.content,
        "category": discussion.category,
        "author": {
            "id": discussion.author_id,
            "name": discussion.author_name,
            "avatar": discussion.author_avatar,
            "role": discussion.author_role,
            "level": discussion.author_level,
            "badges": discussion.author_badges,
            "reputation": discussion.author_reputation,
        },
        "createdAt": discussion.created_at.isoformat(),
        "likes": discussion.likes,
        "comments": discussion.comments,
        "views": discussion.views,
        "isPinned": discussion.is_pinned,
        "isHot": discussion.is_hot,
        "lastActivity": discussion.last_activity.isoformat(),
        "tags": discussion.tags or [],
    }


def _serialize_topic(topic: CommunityTopic) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "category": topic.category,
        "count": topic.count,
        "trend": topic.trend,
    }


def _serialize_event(event: CommunityEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "type": event.event_type,
        "startDate": event.start_date.isoformat(),
        "endDate": event.end_date.isoformat(),
        "attendees": event.attendees,
        "host": {
            "id": event.host_id,
            "name": event.host_name,
            "avatar": event.host_avatar,
            "role": event.host_role,
            "level": event.host_level,
            "badges": event.host_badges,
            "reputation": event.host_reputation,
        },
    }


def _serialize_leaderboard_entry(entry: CommunityLeaderboardEntry) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "avatar": entry.avatar,
        "level": entry.level,
        "points": entry.points,
        "streak": entry.streak,
        "rank": entry.rank,
        "change": entry.change,
    }


class CommunityOverviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _ensure_seed_data()
        query = (request.query_params.get("q") or "").strip().lower()
        category = (request.query_params.get("category") or "all").strip().lower()

        discussions_qs = CommunityDiscussion.objects.all()
        if category != "all":
            discussions_qs = discussions_qs.filter(category=category)

        discussions = [_serialize_discussion(item) for item in discussions_qs]
        if query:
            discussions = [
                item
                for item in discussions
                if query in item.get("title", "").lower()
                or query in item.get("content", "").lower()
                or any(query in str(tag).lower() for tag in item.get("tags", []))
            ]

        topics = [_serialize_topic(item) for item in CommunityTopic.objects.all()]
        events = [_serialize_event(item) for item in CommunityEvent.objects.all()]
        leaderboard = [
            _serialize_leaderboard_entry(item)
            for item in CommunityLeaderboardEntry.objects.all()
        ]

        top_contributors = leaderboard[:3]
        category_rows = CommunityDiscussion.objects.values("category").annotate(count=Count("id"))
        categories_count = {row["category"]: row["count"] for row in category_rows}
        stats = {
            "totalMembers": CustomUser.objects.count(),
            "activeToday": CustomUser.objects.filter(last_login__date=timezone.localdate()).count(),
            "totalDiscussions": CommunityDiscussion.objects.count(),
            "totalComments": CommunityDiscussion.objects.aggregate(total=Sum("comments")).get("total") or 0,
            "topContributors": top_contributors,
            "categoriesCount": categories_count,
        }

        return Response(
            {
                "discussions": discussions,
                "topics": topics,
                "events": events,
                "leaderboard": leaderboard,
                "stats": stats,
            }
        )


class CommunityDiscussionLikeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, discussion_id):
        _ensure_seed_data()
        discussion = CommunityDiscussion.objects.filter(id=str(discussion_id)).first()
        if discussion is None:
            return Response({"error": "Discussion not found."}, status=404)

        CommunityDiscussion.objects.filter(id=discussion.id).update(likes=F("likes") + 1)
        discussion.refresh_from_db(fields=["likes"])
        return Response({"id": discussion.id, "likes": discussion.likes})
