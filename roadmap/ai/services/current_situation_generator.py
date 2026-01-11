from .base_service import BaseAIService
from ai.prompts.personalization.user_context_prompts import UserContextPrompt
from ai.prompts.system_prompts import SystemPrompts
from ai.providers.ollama_provider import OllamaProvider
from ai.utils.parsers import ResponseParser
from ai.utils.formatters import ResponseFormatter

class CurrentSituationGenerator(BaseAIService):

    def __init__(self):
        # Create provider instance with optimal settings for JSON output
        provider = OllamaProvider(
            model='gpt-oss:120b-cloud',
            temperature=0.3,  # Lower temperature for consistent structured output
            max_tokens=2000
        )
        super().__init__(provider)
        
        self.user_context_prompt = UserContextPrompt()
        self.system_prompts = SystemPrompts()
        self.response_parser = ResponseParser()
        self.response_formatter = ResponseFormatter()

    def generate(self, raw_data, user_age, user):
        """
        Take raw user input and generate structured situation data
        """
        job = self.create_job(
            user=user,
            job_type="CURRENT_SITUATION_GENERATION",
            row_data={"raw_data": raw_data, "user_age": user_age},
        )

        try:
            print("Generating AI response...")
            
            # Generate response from AI
            response = self.provider.generate_response(
                prompt=self.user_context_prompt.format(
                    raw_text=raw_data,
                    age=user_age,
                    strict=False
                ),
                system_prompt=self.system_prompts.get_current_situation_prompt(),
            )
            
            print(f"AI Response Content: {response.content[:200]}...")  # Show first 200 chars
            
            # Parse the response
            parsed_data = self.response_parser.parse_current_situation_response(response.content)
            print(f"Parsed data: {parsed_data}") 
            
            # Update job status
            job.status = "COMPLETED"
            job.row_data = parsed_data
            job.save()
            
            # Format and return success response
            return self.response_formatter.format_success(
                job=job,
                raw_response=response.content,
                parsed_data=parsed_data
            )
            
        except Exception as e:
            # job.status = "FAILED"
            # job.error_message = str(e)
            # job.save()
            # print(f"Error in generate: {str(e)}")
            raise ValueError(f"Error generating current situation: {str(e)}") from e