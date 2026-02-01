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
    def parse_json(content):
        """
        Simplified JSON parser that handles both strings and already-parsed dicts.
        """
        import json
        import re
        
        print(f"DEBUG Parser: Input type: {type(content)}")
        
        # If content is already a dict or list, return it directly
        if isinstance(content, (dict, list)):
            print("DEBUG: Content is already parsed, returning directly")
            return content
        
        # If it's bytes, decode to string
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        # Now it should be a string
        if not isinstance(content, str):
            print(f"DEBUG: Content is {type(content)}, value: {content}")
            raise TypeError(f"Expected string, dict, or list, got {type(content)}")
        
        print(f"DEBUG: Cleaning string content, length: {len(content)}")
        
        # Clean the string
        content = content.strip()
        
        # Remove markdown code blocks
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Find JSON in the text
        json_match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        # Parse JSON
        try:
            result = json.loads(content)
            print(f"DEBUG: Successfully parsed JSON, type: {type(result)}")
            return result
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
            print(f"Problematic content: {content[:200]}...")
            # Try to fix common issues
            content = content.replace("'", '"')
            try:
                return json.loads(content)
            except:
                raise ValueError(f"Invalid JSON: {str(e)}")
            
   
  
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
    


class MilestoneParser:
    """Simple milestone parser"""
    
    @staticmethod
    def parse_milestones(response_content):
        """
        Parse milestones from AI response.
        """
        # First parse the JSON using ResponseParser
        parsed = ResponseParser.parse_json(response_content)
        
        print(f"DEBUG PARSER: Parsed type: {type(parsed)}")
        print(f"DEBUG PARSER: Parsed content: {parsed}")
        
        # Extract milestones from parsed data
        milestones = []
        
        if isinstance(parsed, dict):
            # Look for milestones key
            if 'milestones' in parsed and isinstance(parsed['milestones'], list):
                milestones = parsed['milestones']
            elif isinstance(parsed.get('data'), dict) and 'milestones' in parsed['data']:
                milestones = parsed['data']['milestones']
            else:
                # If dict looks like a single milestone, wrap in list
                if 'title' in parsed or 'description' in parsed:
                    milestones = [parsed]
        
        elif isinstance(parsed, list):
            # If list of milestones
            milestones = parsed
        
        print(f"DEBUG PARSER: Extracted {len(milestones)} milestones")
        
        # Validate and return
        return MilestoneParser._validate_milestones(milestones)
    
    @staticmethod
    def _validate_milestones(milestones_list):
        """Simple validation of milestones"""
        if not isinstance(milestones_list, list):
            return []
        
        validated = []
        for i, milestone in enumerate(milestones_list):
            if not isinstance(milestone, dict):
                continue
            
            # Basic validation
            if not milestone.get('title'):
                continue
            
            validated.append({
                'title': str(milestone.get('title', '')).strip(),
                'description': str(milestone.get('description', '')).strip(),
                'success_criteria': milestone.get('success_criteria', []),
                'display_order': milestone.get('display_order', i + 1),
                'priority': milestone.get('priority', 'medium'),
                'month_year': milestone.get('month_year', f'Month {i + 1}'),
                'estimated_duration_days': milestone.get('estimated_duration_days', 30),
                'ai_reasoning': milestone.get('ai_reasoning', ''),
                'related_attributes': milestone.get('related_attributes', [])
            })
        
        return validated



