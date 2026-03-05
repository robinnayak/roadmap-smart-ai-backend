from django.contrib import admin

from .models import AdaptiveRoadmapState, DailyTaskItem, DailyTaskList, DisciplineStreak, HabitCompletion, HabitTracker


admin.site.register(DailyTaskList)
admin.site.register(DailyTaskItem)
admin.site.register(HabitTracker)
admin.site.register(HabitCompletion)
admin.site.register(DisciplineStreak)
admin.site.register(AdaptiveRoadmapState)