# goals/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from authentication.models import UserPersonalDetails
import threading
from ai.services.current_situation_generator import CurrentSituationGenerator
from ai.models import AIProcessingJob
from goal.models import UserCurrentSituationGoal, Goal, GoalAttributes


@receiver(post_save, sender=UserPersonalDetails)
def trigger_ai_situation_analysis(sender, instance, created, **kwargs):
    """
    Automatically trigger AI situation analysis when UserPersonalDetails is saved.
    Creates UserCurrentSituationGoal automatically.
    """
    # Run only when current_situation is provided AND it's changed
    if instance.current_situation and instance.current_situation.strip():
        print(f"Triggering AI analysis for user: {instance.user.email}")
        
        # Run in background thread
        thread = threading.Thread(
            target=_process_and_create_situation_goal,
            args=(instance.user, instance.current_situation, instance.current_age)
        )
        thread.daemon = True
        thread.start()


def _process_and_create_situation_goal(user, current_situation, current_age):
    """
    Process situation data AND create UserCurrentSituationGoal in background
    """
    try:
        print(f"Starting background AI processing for user {user.id}")
        
        # Process the situation
        generator = CurrentSituationGenerator()
        result = generator.generate(
            raw_data=current_situation,
            user_age=current_age,
            user=user
        )
        
        if result and 'data' in result and 'job_id' in result:
            # Get the structured data and job
            structured_data = result.get("data")
            job_id = result.get("job_id")
            
            try:
                job = AIProcessingJob.objects.get(id=job_id)
                
                # Create or update UserCurrentSituationGoal
                situation_goal, created = UserCurrentSituationGoal.objects.get_or_create(
                    ai_processing_job=job,
                    defaults={
                        "current_situation": structured_data,
                        "current_role": structured_data.get("current_role"),
                        "age": structured_data.get("age"),
                        "key_skills": structured_data.get("key_skills"),
                        "main_goals": structured_data.get("main_goals"),
                        "time_availability": structured_data.get("time_availability"),
                        "constraints": structured_data.get("constraints"),
                        "priority_areas": structured_data.get("priority_areas"),
                    }
                )
                
                if not created:
                    # Update existing
                    situation_goal.current_situation = structured_data
                    situation_goal.current_role = structured_data.get("current_role")
                    situation_goal.age = structured_data.get("age")
                    situation_goal.key_skills = structured_data.get("key_skills")
                    situation_goal.main_goals = structured_data.get("main_goals")
                    situation_goal.time_availability = structured_data.get("time_availability")
                    situation_goal.constraints = structured_data.get("constraints")
                    situation_goal.priority_areas = structured_data.get("priority_areas")
                    situation_goal.save()
                
                print(f"UserCurrentSituationGoal {'created' if created else 'updated'} for user {user.id}")
                
            except AIProcessingJob.DoesNotExist:
                print(f"AIProcessingJob {job_id} not found for user {user.id}")
            except Exception as e:
                print(f"Error creating UserCurrentSituationGoal: {e}")
        
        print(f"Background AI processing completed for user {user.id}")
        return result
        
    except Exception as e:
        print(f"Background AI processing failed for user {user.id}: {e}")
        return None
    
    
@receiver(post_save, sender=Goal)
def create_goal_attributes(sender, instance, created, **kwargs):
    print("Starting goal attributes creation...")
    


