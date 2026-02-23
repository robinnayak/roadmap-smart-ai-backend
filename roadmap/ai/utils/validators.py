# roadmap\ai\utils\validators.py


from typing import Dict, Any, List, Tuple
from datetime import datetime, date
import re


class InputValidator:
    """Validate user inputs before AI processing"""
    
    @staticmethod
    def validate_user_goal_input(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate UserGoalInput data
        
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        # Age validation
        current_age = data.get('current_age')
        target_age = data.get('target_age')
        
        if not current_age or current_age < 13:
            errors.append("Current age must be at least 13")
        if not target_age or target_age <= current_age:
            errors.append("Target age must be greater than current age")
        if target_age and current_age and (target_age - current_age) > 50:
            errors.append("Age gap cannot exceed 50 years")
        
        # Timeline validation
        duration = data.get('roadmap_duration_years')
        if not duration or duration < 1:
            errors.append("Roadmap duration must be at least 1 year")
        if duration and duration > 10:
            errors.append("Roadmap duration cannot exceed 10 years")
        
        # Time validation
        daily_hours = data.get('daily_available_hours')
        if not daily_hours or daily_hours < 1:
            errors.append("Must have at least 1 hour available daily")
        if daily_hours and daily_hours > 16:
            errors.append("Daily hours cannot exceed 16")
        
        # Text field validation
        situation = data.get('current_situation', '')
        if len(situation.strip()) < 50:
            errors.append("Current situation must be at least 50 characters")
        
        goals = data.get('life_goals', '')
        if len(goals.strip()) < 50:
            errors.append("Life goals must be at least 50 characters")
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        """Validate date string format (YYYY-MM-DD)"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except:
            return False
    
    @staticmethod
    def validate_priority(priority: str) -> bool:
        """Validate priority value"""
        return priority.lower() in ['high', 'medium', 'low']
    
    @staticmethod
    def validate_category(category: str) -> bool:
        """Validate goal category"""
        return category.lower() in ['financial', 'career', 'health', 'personal']


class OutputValidator:
    """Validate AI outputs before saving to database"""
    
    @staticmethod
    def validate_goal_structure(goal: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a single goal structure"""
        errors = []
        
        # Required fields
        if not goal.get('title'):
            errors.append("Goal must have a title")
        
        if not goal.get('description'):
            errors.append("Goal must have a description")
        
        # Validate category
        category = goal.get('primary_category')
        if not category or not InputValidator.validate_category(category):
            errors.append(f"Invalid category: {category}")
        
        # Validate priority
        priority = goal.get('priority')
        if not priority or not InputValidator.validate_priority(priority):
            errors.append(f"Invalid priority: {priority}")
        
        # Validate date
        target_date = goal.get('target_date')
        if target_date and not InputValidator.validate_date_format(target_date):
            errors.append(f"Invalid date format: {target_date}")
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def validate_goals_batch(goals: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, List[str]]]:
        """Validate multiple goals"""
        all_errors = {}
        
        for i, goal in enumerate(goals):
            is_valid, errors = OutputValidator.validate_goal_structure(goal)
            if not is_valid:
                all_errors[f"goal_{i}"] = errors
        
        return (len(all_errors) == 0, all_errors)

    @staticmethod
    def assess_hierarchy_quality(
        hierarchy: Dict[str, Any],
        timeline_days: int | None = None,
        experience_level: str = "beginner",
        constraints: List[str] | None = None,
    ) -> Dict[str, Any]:
        """
        Heuristic quality report for generated hierarchy.
        Returns scores and issues for:
        - specificity/actionability
        - sequencing
        - realism vs timeline
        - alignment with user constraints/skill level
        """
        constraints = [c.lower() for c in (constraints or [])]
        milestones = hierarchy.get("milestones", []) or []
        tasks = []
        sequencing_ok = True

        for milestone in milestones:
            subgoals = milestone.get("subgoals", []) or []
            previous_week = 0
            for sg in subgoals:
                week = int(sg.get("subgoal_data", {}).get("week_number", 0) or 0)
                if week and previous_week and week < previous_week:
                    sequencing_ok = False
                if week:
                    previous_week = week
                tasks.extend(sg.get("tasks", []) or [])

        action_verbs = (
            "build", "create", "write", "study", "practice", "review", "design",
            "implement", "analyze", "test", "plan", "record", "track", "document",
        )
        specific_tasks = 0
        realistic_tasks = 0
        aligned_tasks = 0

        for task in tasks:
            title = (task.get("title") or "").strip().lower()
            description = (task.get("description") or "").strip().lower()
            minutes = int(task.get("estimated_duration_minutes", 0) or 0)
            task_type = (task.get("task_type") or "").strip().lower()

            has_verb = any(title.startswith(v + " ") for v in action_verbs)
            has_detail = len(description) >= 30
            if has_verb and has_detail and task_type in {"learning", "practice", "project", "review", "assessment"}:
                specific_tasks += 1

            # Basic realism guard by skill level.
            if experience_level.lower() in {"beginner", "novice"}:
                if 15 <= minutes <= 150:
                    realistic_tasks += 1
            else:
                if 15 <= minutes <= 240:
                    realistic_tasks += 1

            # Basic alignment check for common constraints.
            if "limited time" in constraints and minutes > 120:
                continue
            if "low energy" in constraints and minutes > 90:
                continue
            aligned_tasks += 1

        total_tasks = len(tasks)
        specificity_score = round((specific_tasks / max(total_tasks, 1)) * 100)
        realism_score = round((realistic_tasks / max(total_tasks, 1)) * 100)
        alignment_score = round((aligned_tasks / max(total_tasks, 1)) * 100)

        timeline_score = 100
        if timeline_days:
            # Expect at most 1 task per day on average for the hierarchy horizon.
            expected_max_tasks = max(1, timeline_days)
            if total_tasks > expected_max_tasks:
                overflow = total_tasks - expected_max_tasks
                timeline_score = max(0, 100 - round((overflow / expected_max_tasks) * 100))

        overall = round(
            (specificity_score * 0.35)
            + (realism_score * 0.25)
            + (alignment_score * 0.2)
            + ((100 if sequencing_ok else 40) * 0.1)
            + (timeline_score * 0.1)
        )

        issues: List[str] = []
        if specificity_score < 70:
            issues.append("Low specificity/actionability in tasks.")
        if not sequencing_ok:
            issues.append("Subgoal sequencing is not strictly progressive.")
        if realism_score < 70:
            issues.append("Task duration realism is weak for user skill level.")
        if alignment_score < 70:
            issues.append("Tasks do not align well with user constraints.")
        if timeline_score < 70:
            issues.append("Generated workload appears unrealistic for the timeline.")

        return {
            "overall_score": overall,
            "specificity_score": specificity_score,
            "sequencing_score": 100 if sequencing_ok else 40,
            "realism_score": realism_score,
            "alignment_score": alignment_score,
            "timeline_score": timeline_score,
            "issues": issues,
            "feedback_hint": (
                "Collect user feedback on skipped/delayed tasks and feed those "
                "patterns back into prompts for future generations."
            ),
        }
