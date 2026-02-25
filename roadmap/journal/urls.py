from django.urls import path

from journal.views import (
    JournalAutoPhraseAPIView,
    JournalDatesAPIView,
    JournalEntryByDateAPIView,
    JournalSearchAPIView,
    JournalStatsAPIView,
    JournalWordCloudAPIView,
)

urlpatterns = [
    path("entries/", JournalEntryByDateAPIView.as_view(), name="journal-entry-by-date"),
    path("auto-phrase/", JournalAutoPhraseAPIView.as_view(), name="journal-auto-phrase"),
    path("search/", JournalSearchAPIView.as_view(), name="journal-search"),
    path("dates/", JournalDatesAPIView.as_view(), name="journal-dates"),
    path("stats/", JournalStatsAPIView.as_view(), name="journal-stats"),
    path("wordcloud/", JournalWordCloudAPIView.as_view(), name="journal-wordcloud"),
]
