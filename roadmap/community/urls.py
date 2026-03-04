from django.urls import path

from community.views import CommunityDiscussionLikeAPIView, CommunityOverviewAPIView

urlpatterns = [
    path("overview/", CommunityOverviewAPIView.as_view(), name="community-overview"),
    path(
        "discussions/<str:discussion_id>/like/",
        CommunityDiscussionLikeAPIView.as_view(),
        name="community-discussion-like",
    ),
]
