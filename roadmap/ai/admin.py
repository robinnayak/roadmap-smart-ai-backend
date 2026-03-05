from django.contrib import admin

from .models import AIModelUsageStats, AIProcessingJob, AIPromptTemplate


admin.site.register(AIProcessingJob)
admin.site.register(AIModelUsageStats)
admin.site.register(AIPromptTemplate)