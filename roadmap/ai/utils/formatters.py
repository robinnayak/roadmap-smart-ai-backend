# roadmap\ai\utils\formatters.py



import json
from typing import Dict, Any
import re


class ResponseFormatter:
    
    @staticmethod
    def format_success(job, raw_response, parsed_data):
        """Format successful response."""
        return {
            "status": "success",
            "job_id": str(job.id),
            "job_status": job.status,
            "data": parsed_data,
            # "raw_response": raw_response[:500],  # Limit raw response length
        }
    
    @staticmethod
    def format_error(error_message, job=None):
        """Format error response."""
        response = {
            "status": "error",
            "error": error_message,
        }
        if job:
            response["job_id"] = str(job.id)
            response["job_status"] = job.status
        return response
    
    @staticmethod
    def clean_json_response(response_text):
        """
        Clean and extract JSON from AI response.
        Handles markdown code blocks, extra text, and formatting issues.
        """
        if not response_text:
            raise ValueError("Empty response text")
        
        # Remove markdown code blocks
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*', '', response_text)
        
        # Try to find JSON object or array in the text
        json_match = re.search(r'(\{.*\}|\[.*\])', response_text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(1)
        else:
            # If no match, use the whole text
            json_str = response_text.strip()
        
        try:
            # Parse and return the JSON
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON: {str(e)}\nContent: {json_str[:200]}")
    
    @staticmethod
    def format_structured_response(data):
        """Format structured data into readable text."""
        if isinstance(data, dict):
            return "\n".join([f"{k}: {v}" for k, v in data.items()])
        elif isinstance(data, list):
            return "\n".join([f"- {item}" for item in data])
        return str(data)
    
    @staticmethod
    def extract_sections(text, sections):
        """Extract specific sections from text."""
        result = {}
        for section in sections:
            pattern = rf"{section}:\s*(.+?)(?=\n\n|\Z)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                result[section] = match.group(1).strip()
        return result


class GoalFormatter:
    """Format goal-related data"""
    
    @staticmethod
    def format_goal_tree(goals_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format goals with subgoals and steps in tree structure"""
        formatted = {
            'total_goals': len(goals_data.get('goals', [])),
            'goals': []
        }
        
        for goal in goals_data.get('goals', []):
            formatted_goal = {
                'id': goal.get('id'),
                'title': goal.get('title'),
                'category': goal.get('primary_category'),
                'priority': goal.get('priority'),
                'target_date': goal.get('target_date'),
                'subgoals_count': len(goal.get('subgoals', [])),
                'subgoals': []
            }
            
            for subgoal in goal.get('subgoals', []):
                formatted_subgoal = {
                    'title': subgoal.get('title'),
                    'steps_count': len(subgoal.get('steps', [])),
                    'steps': [s.get('title') for s in subgoal.get('steps', [])]
                }
                formatted_goal['subgoals'].append(formatted_subgoal)
            
            formatted['goals'].append(formatted_goal)
        
        return formatted
    
    
    