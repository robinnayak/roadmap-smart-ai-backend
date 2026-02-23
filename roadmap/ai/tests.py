from django.test import TestCase

from ai.utils.validators import OutputValidator


class HierarchyQualityAssessmentTests(TestCase):
    def test_assess_hierarchy_quality_returns_scores_and_detects_issues(self):
        hierarchy = {
            "milestones": [
                {
                    "subgoals": [
                        {
                            "subgoal_data": {"week_number": 2},
                            "tasks": [
                                {
                                    "title": "Learn stuff",
                                    "description": "Short",
                                    "task_type": "learning",
                                    "estimated_duration_minutes": 300,
                                }
                            ],
                        },
                        {
                            "subgoal_data": {"week_number": 1},
                            "tasks": [
                                {
                                    "title": "Practice feature implementation",
                                    "description": "Implement and validate one concrete feature using test data.",
                                    "task_type": "practice",
                                    "estimated_duration_minutes": 90,
                                }
                            ],
                        },
                    ]
                }
            ]
        }

        report = OutputValidator.assess_hierarchy_quality(
            hierarchy=hierarchy,
            timeline_days=2,
            experience_level="beginner",
            constraints=["limited time"],
        )

        self.assertIn("overall_score", report)
        self.assertIn("issues", report)
        self.assertLess(report["sequencing_score"], 100)
        self.assertGreater(len(report["issues"]), 0)
