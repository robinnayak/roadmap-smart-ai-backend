from importlib import import_module


_EXPORT_MAP = {
    "GIEIntakeUnderstandingService": (".intake_understanding", "GIEIntakeUnderstandingService"),
    "GIEDynamicSchemaService": (".dynamic_schema", "GIEDynamicSchemaService"),
    "GIEDialogueManagerService": (".dialogue_manager", "GIEDialogueManagerService"),
    "GIETurnPipelineService": (".turn_pipeline", "GIETurnPipelineService"),
    "GIEPlanningService": (".planning", "GIEPlanningService"),
    "GIEAdaptationService": (".adaptation", "GIEAdaptationService"),
    "GIETimelineValidationService": (".timeline_validation", "GIETimelineValidationService"),
    "GIETimelineFeasibilityService": (".timeline_feasibility", "GIETimelineFeasibilityService"),
    "GIEUnifiedContextService": (".unified_context", "GIEUnifiedContextService"),
    "GIEHabitRankingService": (".habit_ranking", "GIEHabitRankingService"),
    "GIEObservabilityService": (".observability", "GIEObservabilityService"),
    "GIERolloutPolicyService": (".rollout", "GIERolloutPolicyService"),
    "map_goal_domain_to_primary_category": (".turn_pipeline", "map_goal_domain_to_primary_category"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name: str):
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORT_MAP[name]
    module = import_module(module_name, package=__name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
