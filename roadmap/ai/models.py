from django.db import models

# Create your models here.


class AIProcessingJob(models.Model):
    """Model representing an AI processing job."""
    
    JOB_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    user = models.ForeignKey('authentication.CustomUser', on_delete=models.CASCADE)
    job_type = models.CharField(max_length=100)
    row_data = models.JSONField()
    status = models.CharField(max_length=20, choices=JOB_STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Job {self.id} - {self.job_type} - {self.status}"