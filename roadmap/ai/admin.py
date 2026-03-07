from django.contrib import admin

from .models import (
    AIModelUsageStats,
    AIProcessingJob,
    AIPromptTemplate,
    AIReengagementAction,
    AIUserChurnState,
)


admin.site.register(AIProcessingJob)
admin.site.register(AIModelUsageStats)
admin.site.register(AIPromptTemplate)
admin.site.register(AIUserChurnState)
admin.site.register(AIReengagementAction)
