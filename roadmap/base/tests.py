from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from .models import WaitlistEntry


class WaitlistApiTests(APITestCase):
    def test_waitlist_count_returns_total_entries(self):
        WaitlistEntry.objects.create(email="first@example.com")
        WaitlistEntry.objects.create(email="second@example.com")

        response = self.client.get("/waitlist/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["count"], 2)

    @patch("base.views.send_email_via_resend")
    def test_waitlist_signup_creates_entry_and_returns_count(self, send_email_mock):
        response = self.client.post(
            "/waitlist/",
            {"email": "NewUser@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["count"], 1)
        self.assertTrue(payload["data"]["created"])
        self.assertEqual(payload["data"]["email"], "newuser@example.com")
        self.assertTrue(WaitlistEntry.objects.filter(email="newuser@example.com").exists())
        send_email_mock.assert_called_once()
        self.assertEqual(send_email_mock.call_args.kwargs["to_email"], "newuser@example.com")

    @patch("base.views.send_email_via_resend")
    def test_waitlist_signup_is_idempotent_for_existing_email(self, send_email_mock):
        WaitlistEntry.objects.create(email="repeat@example.com")

        response = self.client.post(
            "/waitlist/",
            {"email": "REPEAT@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["count"], 1)
        self.assertFalse(payload["data"]["created"])
        self.assertEqual(WaitlistEntry.objects.filter(email="repeat@example.com").count(), 1)
        send_email_mock.assert_not_called()

    def test_waitlist_signup_rejects_invalid_email(self):
        response = self.client.post(
            "/waitlist/",
            {"email": "not-an-email"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "validation_error")
        self.assertIn("email", payload["errors"])
