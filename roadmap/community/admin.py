from django.contrib import admin

from .models import CommunityDiscussion, CommunityEvent, CommunityLeaderboardEntry, CommunityTopic


admin.site.register(CommunityDiscussion)
admin.site.register(CommunityTopic)
admin.site.register(CommunityEvent)
admin.site.register(CommunityLeaderboardEntry)