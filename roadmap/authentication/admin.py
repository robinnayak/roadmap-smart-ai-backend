from django.contrib import admin
from .models import CustomUser, Profile, NotificationSettings


# Register your models here.

class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'username', 'is_staff', 'is_active')
    search_fields = ('email', 'username')
    ordering = ('email',)

admin.site.register(CustomUser, CustomUserAdmin)

admin.site.register(Profile)
admin.site.register(NotificationSettings)
