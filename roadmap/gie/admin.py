from django.contrib import admin

from gie.models import GIEPlanSnapshot, GIESession, GIESlotDefinition, GIESlotState, GIETurn


@admin.register(GIESession)
class GIESessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'goal_domain', 'status', 'phase', 'updated_at')
    list_filter = ('status', 'phase', 'goal_domain')
    search_fields = ('user__email', 'goal_text')


@admin.register(GIETurn)
class GIETurnAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'turn_index', 'role', 'kind', 'applied', 'created_at')
    list_filter = ('role', 'kind', 'applied')
    search_fields = ('session__id', 'content', 'client_turn_id')


@admin.register(GIESlotDefinition)
class GIESlotDefinitionAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'key', 'required', 'data_type', 'updated_at')
    list_filter = ('required', 'data_type')
    search_fields = ('session__id', 'key', 'label')


@admin.register(GIESlotState)
class GIESlotStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'slot_key', 'status', 'required', 'source', 'updated_at')
    list_filter = ('status', 'required', 'source')
    search_fields = ('session__id', 'slot_key')


@admin.register(GIEPlanSnapshot)
class GIEPlanSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('session__id', 'goal_summary')
