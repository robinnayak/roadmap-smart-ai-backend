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