# roadmap\ai\utils\parsers.py


import json
import re
from typing import Dict, Any, Optional, List


class ResponseParser:
    """Parse and validate AI responses"""
    
    @staticmethod
    def parse_current_situation_response(response_content):
        """Parse current situation response from AI."""
        try:
            # Clean the response
            cleaned = ResponseParser._clean_json_response(response_content)
            
            # Parse JSON
            data = json.loads(cleaned)
            
            # Validate required fields
            # required_fields = ['current_role', 'main_goals', 'key_skills']
            # for field in required_fields:
            #     if field not in data:
            #         raise ValueError(f"Missing required field: {field}")
            
            return data
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            raise ValueError(f"Error parsing response: {str(e)}")
    
    @staticmethod
    def _clean_json_response(response_text):
        """Clean JSON from markdown and extra text."""
        if not response_text:
            raise ValueError("Empty response text")
        
        # Remove markdown code blocks
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*', '', response_text)
        
        # Find JSON object in the text
        json_match = re.search(r'(\{.*\})', response_text, re.DOTALL)
        
        if json_match:
            return json_match.group(1).strip()
        
        # If no match, return cleaned text
        return response_text.strip()
    
    @staticmethod
    def parse_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON from AI response
        Handles markdown code blocks and malformed JSON
        """
        from .formatters import ResponseFormatter
        
        # Clean the response
        cleaned = ResponseFormatter.clean_json_response(text)
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Try to fix common issues
            # Fix single quotes
            cleaned = cleaned.replace("'", '"')
            try:
                return json.loads(cleaned)
            except:
                raise ValueError(f"Could not parse JSON: {str(e)}\nText: {cleaned[:200]}")
    
    @staticmethod
    def parse_goals(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse and validate goals from JSON"""
        goals = json_data.get('goals', [])
        
        validated_goals = []
        for goal in goals:
            if not goal.get('title'):
                continue
            
            validated_goal = {
                'title': goal.get('title', '').strip(),
                'description': goal.get('description', '').strip(),
                'primary_category': goal.get('primary_category', 'personal'),
                'priority': goal.get('priority', 'medium'),
                'target_date': goal.get('target_date'),
                'why_it_matters': goal.get('why_it_matters', ''),
                'subgoals': ResponseParser.parse_subgoals(goal.get('subgoals', []))
            }
            validated_goals.append(validated_goal)
        
        return validated_goals
    
    @staticmethod
    def parse_subgoals(subgoals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse and validate subgoals"""
        validated = []
        for subgoal in subgoals:
            if not subgoal.get('title'):
                continue
            
            validated_subgoal = {
                'title': subgoal.get('title', '').strip(),
                'description': subgoal.get('description', '').strip(),
                'target_date': subgoal.get('target_date'),
                'steps': ResponseParser.parse_steps(subgoal.get('steps', []))
            }
            validated.append(validated_subgoal)
        
        return validated
    
    @staticmethod
    def parse_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse and validate steps"""
        validated = []
        for step in steps:
            if not step.get('title'):
                continue
            
            validated_step = {
                'title': step.get('title', '').strip(),
                'description': step.get('description', '').strip(),
                'instructions': step.get('instructions', '').strip(),
            }
            validated.append(validated_step)
        
        return validated
    
    @staticmethod
    def extract_sentiment_score(text: str) -> float:
        """Extract sentiment score from analysis text"""
        # Look for patterns like "sentiment: 0.75" or "score: 0.75"
        patterns = [
            r'sentiment[:\s]+(-?\d+\.?\d*)',
            r'score[:\s]+(-?\d+\.?\d*)',
            r'(-?\d+\.?\d*)(?:\s+(?:sentiment|score))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                try:
                    score = float(match.group(1))
                    # Clamp to -1.0 to 1.0
                    return max(-1.0, min(1.0, score))
                except:
                    continue
        
        return 0.0  # Neutral if can't parse