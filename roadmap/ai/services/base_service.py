from ai.providers.ollama_provider import OllamaProvider
from ai.models import AIProcessingJob


class BaseAIService:
    """Base class for AI services."""
    
    def __init__(self, provider: OllamaProvider):
        self.provider = provider
        
    def create_job(self, user, job_type, row_data):
        """Create a new AI job."""
        print("creating job...")
        print(f"User: {user}")  # Debug
        print(f"Job type: {job_type}")  # Debug
        
        
        existing_job = AIProcessingJob.objects.filter(
            user=user,
            job_type=job_type
        ).first()
        
        print(f"Existing job: {existing_job}")  # Debug
        if existing_job:
            existing_job.row_data = row_data
            existing_job.save()
            return existing_job, False

        
        
        job = AIProcessingJob.objects.create(
            user=user,
            job_type=job_type,
            row_data=row_data,
            status='PENDING'
        )
        return job, True
    
    
    
        