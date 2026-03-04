from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser


class ResponseContractTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="contract-shape@test.com",
            password="Password@123",
        )

    def test_base_endpoint_uses_standard_success_fields(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("data", payload)

    def test_routine_error_response_uses_standard_error_fields(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/routines/progress/?date=invalid-date")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("error", payload)

    def test_community_success_response_preserves_legacy_keys_and_contract(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/community/overview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("data", payload)
        self.assertIn("discussions", payload)

    def test_ai_success_response_has_standard_contract(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/ai/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("data", payload)

    def test_auth_endpoint_response_has_standard_contract(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/auth/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("data", payload)

    def test_journal_stats_success_response_has_standard_contract(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/journal/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn("message", payload)
        self.assertIn("data", payload)
