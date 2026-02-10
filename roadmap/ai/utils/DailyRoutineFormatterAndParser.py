import json
import re



class DailyRoutineFormatter:
    """Matches BaseFormatter pattern"""
    
    @staticmethod
    def format_success(data, message):
        """Same signature as BaseFormatter.format_success"""
        return {
            "status": "success",
            "message": message,
            "data": data
        }
    
    @staticmethod
    def format_error(error_message, error_code=None):
        """Same signature as BaseFormatter.format_error"""
        response = {
            "status": "error",
            "error": error_message
        }
        if error_code:
            response["error_code"] = error_code
        return response


class DailyRoutineParser:
    """Simple parser for daily routine AI responses"""
    
    @staticmethod
    def parse_response(text):
        """Parse AI response - just clean JSON"""
        try:
            # Remove code blocks
            text = text.replace('```json', '').replace('```', '').strip()
            
            # Parse JSON
            data = json.loads(text)
            
            # Validate structure
            if not isinstance(data, dict):
                raise ValueError("Response must be JSON object")
            
            return data
            
        except json.JSONDecodeError as e:
            # Try to extract JSON
            match = re.search(r'(\{.*\})', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except:
                    raise ValueError(f"Invalid JSON: {str(e)}")
            raise
    
    @staticmethod
    def validate_daily_routine(data):
        """Validate daily routine structure"""
        if "tasks" not in data:
            data["tasks"] = []
        
        if "motivation" not in data:
            data["motivation"] = "You can do this!"
        
        if "mantra" not in data:
            data["mantra"] = "Stay focused"
        
        # Calculate total minutes
        total = sum(task.get("estimated_minutes", 30) for task in data.get("tasks", []))
        data["total_estimated_minutes"] = total
        
        return data