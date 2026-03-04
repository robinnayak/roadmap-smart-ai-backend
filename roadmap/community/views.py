from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


MOCK_COMMUNITY_PAYLOAD = {
    "discussions": [
        {
            "id": "1",
            "title": "How to stay consistent with morning routine?",
            "content": "I have been struggling to wake up early consistently. Any tips?",
            "category": "routines",
            "author": {
                "id": "u1",
                "name": "Alex Chen",
                "avatar": "https://i.pravatar.cc/150?u=1",
                "role": "member",
                "level": 12,
                "badges": 5,
                "reputation": 450,
            },
            "createdAt": "2024-02-21T08:30:00Z",
            "likes": 24,
            "comments": 15,
            "views": 342,
            "isPinned": False,
            "isHot": True,
            "lastActivity": "2024-02-21T14:20:00Z",
            "tags": ["morning-routine", "discipline", "habits"],
        },
        {
            "id": "2",
            "title": "30-Day Productivity Challenge - Join Us!",
            "content": "Starting March 1st, we are doing a 30-day productivity challenge.",
            "category": "motivation",
            "author": {
                "id": "u2",
                "name": "Sarah Johnson",
                "avatar": "https://i.pravatar.cc/150?u=2",
                "role": "contributor",
                "level": 24,
                "badges": 12,
                "reputation": 1250,
            },
            "createdAt": "2024-02-20T10:15:00Z",
            "likes": 156,
            "comments": 67,
            "views": 1234,
            "isPinned": True,
            "isHot": True,
            "lastActivity": "2024-02-21T15:45:00Z",
            "tags": ["challenge", "productivity", "community"],
        },
        {
            "id": "3",
            "title": "How do you track your habits effectively?",
            "content": "Looking for recommendations on habit tracking methods that work.",
            "category": "habits",
            "author": {
                "id": "u3",
                "name": "Emily Zhang",
                "avatar": "https://i.pravatar.cc/150?u=3",
                "role": "member",
                "level": 15,
                "badges": 7,
                "reputation": 680,
            },
            "createdAt": "2024-02-20T16:20:00Z",
            "likes": 34,
            "comments": 28,
            "views": 456,
            "isPinned": False,
            "isHot": False,
            "lastActivity": "2024-02-21T11:30:00Z",
            "tags": ["habits", "tracking", "tools"],
        },
    ],
    "topics": [
        {"id": "t1", "name": "Morning Routines", "category": "routines", "count": 234, "trend": "up"},
        {"id": "t2", "name": "Goal Setting", "category": "goals", "count": 567, "trend": "up"},
        {"id": "t3", "name": "Habit Formation", "category": "habits", "count": 345, "trend": "up"},
    ],
    "events": [
        {
            "id": "e1",
            "title": "Weekly Community Meetup",
            "description": "Virtual coffee chat to connect with fellow goal-crushers",
            "type": "meetup",
            "startDate": "2024-02-23T15:00:00Z",
            "endDate": "2024-02-23T16:30:00Z",
            "attendees": 89,
            "host": {
                "id": "u5",
                "name": "David Kim",
                "avatar": "https://i.pravatar.cc/150?u=5",
                "role": "moderator",
                "level": 32,
                "badges": 18,
                "reputation": 2450,
            },
        }
    ],
    "leaderboard": [
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
    ],
    "stats": {
        "totalMembers": 15432,
        "activeToday": 1245,
        "totalDiscussions": 2341,
        "totalComments": 15678,
        "topContributors": [
            {
                "id": "u5",
                "name": "David Kim",
                "avatar": "https://i.pravatar.cc/150?u=5",
                "role": "moderator",
                "level": 32,
                "badges": 18,
                "reputation": 2450,
            }
        ],
        "categoriesCount": {
            "general": 567,
            "goals": 432,
            "routines": 345,
            "habits": 289,
            "motivation": 234,
            "achievements": 178,
            "questions": 156,
        },
    },
}


class CommunityOverviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip().lower()
        category = (request.query_params.get("category") or "all").strip().lower()

        discussions = MOCK_COMMUNITY_PAYLOAD["discussions"]

        if category != "all":
            discussions = [d for d in discussions if d.get("category") == category]

        if query:
            discussions = [
                d
                for d in discussions
                if query in d.get("title", "").lower()
                or query in d.get("content", "").lower()
                or any(query in tag.lower() for tag in d.get("tags", []))
            ]

        return Response(
            {
                "discussions": discussions,
                "topics": MOCK_COMMUNITY_PAYLOAD["topics"],
                "events": MOCK_COMMUNITY_PAYLOAD["events"],
                "leaderboard": MOCK_COMMUNITY_PAYLOAD["leaderboard"],
                "stats": MOCK_COMMUNITY_PAYLOAD["stats"],
            }
        )


class CommunityDiscussionLikeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, discussion_id):
        discussion = next(
            (d for d in MOCK_COMMUNITY_PAYLOAD["discussions"] if d["id"] == str(discussion_id)),
            None,
        )
        if discussion is None:
            return Response({"error": "Discussion not found."}, status=404)

        discussion["likes"] += 1
        return Response({"id": discussion["id"], "likes": discussion["likes"]})
