from django.contrib import admin

from .models import CommitmentContract, Goal, GoalAttributes, Milestone, SubGoal, Task, UserCurrentSituationGoal


admin.site.register(UserCurrentSituationGoal)
admin.site.register(Goal)
admin.site.register(CommitmentContract)
admin.site.register(GoalAttributes)
admin.site.register(Milestone)
admin.site.register(SubGoal)
admin.site.register(Task)