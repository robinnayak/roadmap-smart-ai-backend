from django.contrib import admin
from .models import (
    DailyTaskList, DailyTaskItem, HabitTracker,
    HabitCompletion, DisciplineStreak
)


# Register your models here.

admin.site.register(DailyTaskList)
admin.site.register(DailyTaskItem)
admin.site.register(HabitTracker)
admin.site.register(HabitCompletion)
admin.site.register(DisciplineStreak)

