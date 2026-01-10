# roadmap\ai\prompts\base_prompts.py



class BasePrompt:
    def __init__(self):
        self.template = ""
        self.required_variables = []
        
        
    def format(self, **kwargs):
        """
        Format prompt with provided variables
        
        Args:
            **kwargs: Variables to insert into template
            
        Returns:
            Formatted prompt string
        """
        
        missing_vars = [ var for var in self.required_variables if var not in kwargs]
        if missing_vars:
            raise ValueError(f"Missing required variables for prompt: {', '.join(missing_vars)}")
        
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Error formatting prompt: missing variable {str(e)}")
        
    
    def validate_context(self, context):
        return all(var in context for var in self.required_variables)


class StructuredOutputPrompt(BasePrompt):
    """Prompt that requests structured JSON output"""
    
    def __init__(self, output_schema):
        super().__init__()
        self.output_schema = output_schema
        
    def format(self, **kwargs):
        """Format with json schema instruction"""
        
        base_prompt = super().format(**kwargs)
        schema_instruction = f"""
            IMPORTANT: Respond only with valid JSON matching this exact schema:
            {self._format_schema()}
        """
        return f"{base_prompt}\n\n{schema_instruction}"
    
    def _format_schema(self):
        import json
        return json.dumps(self.output_schema, indent=4)