from ai.providers.ollama_provider import OllamaProvider
from ai.models import AIProcessingJob


class BaseAIService:
    """Base class for AI services."""
    
    def __init__(self, provider: OllamaProvider):
        self.provider = provider
        
    def create_job(self, user, job_type, row_data):
        """Create a new AI job."""
        return AIProcessingJob.objects.create(
            user=user,
            job_type=job_type,
            row_data=row_data,
            status='PENDING'
        )
    
    
        