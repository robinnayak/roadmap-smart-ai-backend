from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from roadmap.settings import (
    BROWSABLE_RENDERER_CLASS,
    JSON_RENDERER_CLASS,
    build_default_renderer_classes,
    build_logging_config,
)
from roadmap.urls import build_urlpatterns


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

    def test_health_endpoint_returns_standard_success_contract(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["status"], "ok")


class EnvironmentContractTests(APITestCase):
    def test_build_urlpatterns_excludes_api_auth_when_debug_false(self):
        patterns = build_urlpatterns(debug=False)
        self.assertNotIn("api-auth/", [str(pattern.pattern) for pattern in patterns])

    def test_build_urlpatterns_includes_api_auth_when_debug_true(self):
        patterns = build_urlpatterns(debug=True)
        self.assertIn("api-auth/", [str(pattern.pattern) for pattern in patterns])

    def test_renderer_classes_are_json_only_in_production_contract(self):
        self.assertEqual(build_default_renderer_classes(debug=False), [JSON_RENDERER_CLASS])

    def test_renderer_classes_add_browsable_renderer_in_debug_contract(self):
        self.assertEqual(
            build_default_renderer_classes(debug=True),
            [JSON_RENDERER_CLASS, BROWSABLE_RENDERER_CLASS],
        )

    def test_logging_contract_is_console_only(self):
        logging_config = build_logging_config()
        self.assertEqual(set(logging_config["handlers"].keys()), {"console"})
        self.assertFalse(any("FileHandler" in handler.get("class", "") for handler in logging_config["handlers"].values()))
