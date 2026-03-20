import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from datetime import timedelta
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.serializers.json import DjangoJSONEncoder
from django.core import signing
from rest_framework.test import APITestCase
from django.urls import reverse
# from django.test import Client
from rest_framework.test import APIClient as Client
from rest_framework_simplejwt.tokens import RefreshToken
from django.test import override_settings
from django.core.cache import cache
from rest_framework import status 

from authentication.models import NotificationSettings, UserPersonalDetails

User = get_user_model()


class UserRegistrationTestCase(APITestCase):
    """
        Test cases for User Registration API endpoint.

        Validations scenario:
    1. Successful registration with valid data.
    2. Registration failure with missing required fields (e.g., username, email, password).
    3. Registration failure with invalid email format.
    4. Registration failure with password mismatch (password and password2 do not match).
    5. Registration failure with existing username or email (duplicate entries).

    """

    def setUp(self):
        self.url = reverse("user-register")
        self.client = Client()

        self.valid_data = {
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "testpassword",
            "password2": "testpassword",
        }

        cache.clear()

    # =========================== SUCCESS CASES =========================

    def test_valid_registration(self):
        response = self.client.post(
            self.url, 
            data=self.valid_data, 
            content_type="application/json"
        )

        # self.assertEqual(response.status_code, )
        self.assertIn("data", response.data)
        self.assertIn("tokens", response.data['data'])
        self.assertIn("user", response.data['data'])
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['user']['email'], 'testuser@example.com')
        self.assertEqual(response.data['data']['user']['username'], 'testuser')
        self.assertIn('access', response.data['data']['tokens'])
        self.assertIn('refresh', response.data['data']['tokens'])
        
        
        #verify user was created in the database
        self.assertTrue(User.objects.filter(username="testuser").exists())
        
        
    # ============================ FAILURE CASES =========================
    
    def test_registration_with_missing_fields(self):
        test_cases = [
            # Missing email
            {"password": "StrongPass123!", "password2": "StrongPass123!"},
            # Missing password
            {"email": "test@example.com", "password2": "StrongPass123!"},
            # Missing password2
            {"email": "test@example.com", "password": "StrongPass123!"},
            # Empty JSON
            {},
            # None/null values
            {"email": None, "password": "StrongPass123!", "password2": "StrongPass123!"},
        ]
        
        for i, data in enumerate(test_cases):
            with self.subTest(test_cases = f"Missing Fields test {i}"):
                response = self.client.post(
                    self.url, 
                    data=data,
                    content_type="application/json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn('errors', response.data)
                self.assertFalse(response.data['success'])
                
                # for field, error_list in response.data["errors"].items():
                #     for error in error_list:
                #         print(f"Error for field '{field}', Message: {error}, code: {error.code}")
                
        # ============================ password mismatch =========================
    def test_registration_with_password_mismatch(self):
        data = {
            "email": "test@example.com",
            "password": "StrongPass123!",
            "password2": "DifferentPass456!"
        }
    
        response = self.client.post(
            self.url, 
            data=data,
            content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('errors', response.data)
        self.assertFalse(response.data['success'])
        self.assertIn('password', response.data['errors'])
        self.assertIn("The two password fields didn't match.", response.data['errors']['password'])
        
    
    # edge cases 
    
    def test_registration_with_insensitive_email_duplicate(self):
        
        User.objects.create_user(
            username="existinguser",
            email="existing@example.com",
            password="ExistingPass123!"
        )
        
        data = {
            "email": "existing@EXAMPLE.COM",
            "password": "ExistingPass123!",
            "password2": "ExistingPass123!"
        }
    
        response = self.client.post(
            self.url, 
            data=data,
            content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('errors', response.data)
        self.assertFalse(response.data['success'])
        self.assertIn('email', response.data['errors'])
        # self.assertIn("A user with that email already exists.", response.data['errors']['email'])
    

    # weak password 
    
    # def test_registration_with_weak_password(self):
    #     weak_passwords = [
    #         "short",  # Too short
    #         "12345678",  # Only numbers
    #         "abcdefgh",  # Only letters
    #         "password",  # Common password
    #         "aaaaaaaa",  # Repeated characters
    #         "test@123",  # Contains email part
    #     ]
        
    #     for password in weak_passwords:
    #         with self.subTest(password= password):
    #             data = {
    #                 "email": "test@example.com",
    #                 "password": password,
    #                 "password2": password
    #             }
    #             response = self.client.post(
    #                 self.url, 
    #                 data=data,
    #                 content_type="application/json"
    #             )
    #             self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    #             self.assertIn('errors', response.data)
    #             self.assertFalse(response.data['success'])
    #             self.assertIn('password', response.data['errors'])
    #             # You can also check for specific error messages if your password validator provides them
                
                
    def test_rate_limiting(self):
        """
        Test that rate limiting works for registration endpoint
        """
        rate_limited = False
        # Make multiple rapid registration attempts
        for i in range(20):  # Adjust based on your rate limit
            data = {
                **self.valid_data,
                "email": f"test{i}@example.com"
            }
            
            response = self.client.post(
                self.url,
                data=json.dumps(data),
                content_type='application/json'
            )
            
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                rate_limited = True
                # Rate limit triggered
                self.assertIn('error', response.data)
                break
        # self.assertTrue(rate_limited, "Rate limiting was not triggered within the expected number of requests")


class AccountActivationLifecycleTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="lifecycle@example.com",
            password="StrongPass123!",
            username="lifecycle",
        )
        self.login_url = reverse("user-login")
        self.deactivate_url = reverse("user-profile-deactivate")
        self.reactivate_url = reverse("user-profile-reactivate")

    def _login(self):
        return self.client.post(
            self.login_url,
            data={"email": self.user.email, "password": "StrongPass123!"},
            format="json",
        )

    def _login_for_access_token(self):
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["tokens"]["access"]

    def test_deactivate_success_sets_user_inactive(self):
        access = self._login_for_access_token()
        response = self.client.post(
            self.deactivate_url,
            data={},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("deactivated", response.data["message"].lower())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_deactivate_requires_authentication(self):
        response = self.client.post(self.deactivate_url, data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deactivate_when_already_deactivated_returns_conflict(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.deactivate_url,
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "already_deactivated")
        self.client.force_authenticate(user=None)

    def test_login_for_deactivated_user_returns_reactivation_path(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "account_deactivated")
        self.assertIn("reactivation", response.data)
        self.assertIn("reactivation_token", response.data["reactivation"])

    def test_reactivate_success_for_deactivated_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        login_response = self._login()
        token = login_response.data["reactivation"]["reactivation_token"]

        response = self.client.post(
            self.reactivate_url,
            data={"reactivation_token": token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("tokens", response.data["data"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_reactivate_with_invalid_token_returns_error(self):
        response = self.client.post(
            self.reactivate_url,
            data={"reactivation_token": "bad-token"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_or_expired_token")

    @patch("authentication.views.signing.TimestampSigner.unsign")
    def test_reactivate_with_expired_token_returns_error(self, unsign_mock):
        unsign_mock.side_effect = signing.SignatureExpired("expired")
        response = self.client.post(
            self.reactivate_url,
            data={"reactivation_token": "expired-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_or_expired_token")

    def test_reactivate_when_already_active_returns_conflict(self):
        login_response = self._login()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        deactivated_login = self._login()
        token = deactivated_login.data["reactivation"]["reactivation_token"]
        self.client.post(self.reactivate_url, data={"reactivation_token": token}, format="json")

        active_response = self.client.post(
            self.reactivate_url,
            data={"reactivation_token": token},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertEqual(active_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(active_response.data["code"], "already_active")

    def test_deactivate_reactivate_lifecycle_allows_login_again(self):
        access = self._login_for_access_token()
        deactivate_response = self.client.post(
            self.deactivate_url,
            data={},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access}",
        )
        self.assertEqual(deactivate_response.status_code, status.HTTP_200_OK)

        blocked_login = self._login()
        self.assertEqual(blocked_login.status_code, status.HTTP_403_FORBIDDEN)
        token = blocked_login.data["reactivation"]["reactivation_token"]

        reactivate_response = self.client.post(
            self.reactivate_url,
            data={"reactivation_token": token},
            format="json",
        )
        self.assertEqual(reactivate_response.status_code, status.HTTP_200_OK)

        final_login = self._login()
        self.assertEqual(final_login.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", final_login.data)


class ProfilePersonalNotificationEndpointTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="profiletest@example.com",
            password="StrongPass123!",
        )
        self.notification_url = reverse("user-notification")
        self.client.force_authenticate(user=self.user)

    def test_personal_details_put_without_existing_record_returns_404_envelope(self):
        url = reverse("user-personal-details")
        payload = {
            "date_of_birth": "2000-01-01",
            "roadmap_start_date": str(timezone.now().date() + timedelta(days=2)),
            "current_situation": "Working toward a stronger career transition.",
        }
        response = self.client.put(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "details_not_found")

    def test_personal_details_delete_without_existing_record_returns_404_envelope(self):
        url = reverse("user-personal-details")
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "details_not_found")

    def test_personal_details_put_allows_existing_past_roadmap_start_date_when_unchanged(self):
        url = reverse("user-personal-details")
        past_start_date = timezone.now().date() - timedelta(days=5)
        date_of_birth = timezone.now().date() - timedelta(days=9000)
        details = UserPersonalDetails.objects.create(
            user=self.user,
            date_of_birth=date_of_birth,
            roadmap_start_date=past_start_date,
            current_situation="Current role and constraints.",
        )

        payload = {
            "date_of_birth": str(details.date_of_birth),
            "roadmap_start_date": str(details.roadmap_start_date),
            "current_situation": "Updated current role and constraints.",
        }
        response = self.client.put(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["roadmap_start_date"],
            str(past_start_date),
        )
        self.assertEqual(
            response.data["data"]["current_situation"],
            payload["current_situation"],
        )

    def test_personal_details_put_rejects_roadmap_start_date_change(self):
        url = reverse("user-personal-details")
        current_start_date = timezone.now().date() + timedelta(days=2)
        date_of_birth = timezone.now().date() - timedelta(days=9000)
        details = UserPersonalDetails.objects.create(
            user=self.user,
            date_of_birth=date_of_birth,
            roadmap_start_date=current_start_date,
            current_situation="Current role and constraints.",
        )

        payload = {
            "date_of_birth": str(details.date_of_birth),
            "roadmap_start_date": str(current_start_date + timedelta(days=1)),
            "current_situation": "Updated current role and constraints.",
        }
        response = self.client.put(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_data")
        self.assertIn("roadmap_start_date", response.data["errors"])

    def test_notification_get_uses_standard_success_envelope(self):
        response = self.client.get(self.notification_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        self.assertIn("notifications_enabled", response.data["data"])

    def test_notification_put_invalid_payload_returns_standard_error_envelope(self):
        response = self.client.put(
            self.notification_url,
            data={"notifications_enabled": "not-a-boolean"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_data")
        self.assertIn("errors", response.data)

    def test_notification_get_requires_authentication_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.notification_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_notification_put_requires_authentication_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.put(
            self.notification_url,
            data={"notifications_enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_notification_put_success_updates_settings_and_returns_success_envelope(self):
        payload = {
            "notifications_enabled": False,
            "routine_remainders": False,
            "streak_warnings": False,
            "personalize_assistant": False,
            "push_notifications": False,
            "email_notifications": True,
        }
        response = self.client.put(self.notification_url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        for key, value in payload.items():
            self.assertEqual(response.data["data"][key], value)

        notification = NotificationSettings.objects.get(user=self.user)
        self.assertEqual(notification.notifications_enabled, payload["notifications_enabled"])
        self.assertEqual(notification.routine_remainders, payload["routine_remainders"])
        self.assertEqual(notification.streak_warnings, payload["streak_warnings"])
        self.assertEqual(notification.personalize_assistant, payload["personalize_assistant"])
        self.assertEqual(notification.push_notifications, payload["push_notifications"])
        self.assertEqual(notification.email_notifications, payload["email_notifications"])

    @patch("authentication.views.NotificationSettings.objects.get_or_create")
    def test_notification_get_failure_returns_retrieval_error_contract(self, get_or_create_mock):
        get_or_create_mock.side_effect = Exception("boom")
        response = self.client.get(self.notification_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "notification_retrieval_error")
        self.assertIn("errors", response.data)

    def test_profile_password_change_with_invalid_current_password_returns_error(self):
        url = reverse("change-password")
        response = self.client.post(
            url,
            data={
                "current_password": "WrongPass123!",
                "new_password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_current_password")
        self.assertEqual(response.data["message"], "current password not matched.")
        self.assertIn("current_password", response.data["errors"])

    def test_profile_password_change_success_updates_password(self):
        url = reverse("change-password")
        response = self.client.post(
            url,
            data={
                "current_password": "StrongPass123!",
                "new_password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Password updated successfully.")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass123!"))

    def test_profile_put_with_password_fields_returns_endpoint_guidance_error(self):
        url = reverse("user-profile")
        response = self.client.put(
            url,
            data={
                "current_password": "StrongPass123!",
                "new_password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_data")
        self.assertEqual(
            response.data["message"],
            "Use /auth/change-password/ endpoint for password updates.",
        )
        

class ForgotPasswordEndpointTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("forgot-password")
        self.user = User.objects.create_user(
            email="forgot@test.com",
            password="Password@123",
        )

    @patch("authentication.views.send_mail")
    def test_forgot_password_existing_email_returns_generic_success_and_sends_mail(
        self, send_mail_mock
    ):
        send_mail_mock.return_value = 1
        response = self.client.post(
            self.url,
            data={"email": self.user.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("If an account exists for this email", response.data["message"])
        send_mail_mock.assert_called_once()
        _, kwargs = send_mail_mock.call_args
        self.assertIn("uid=", kwargs["message"])
        self.assertIn("token=", kwargs["message"])
        self.assertEqual(kwargs["recipient_list"], [self.user.email])

    @patch("authentication.views.send_mail")
    def test_forgot_password_unknown_email_returns_same_generic_success(
        self, send_mail_mock
    ):
        response = self.client.post(
            self.url,
            data={"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("If an account exists for this email", response.data["message"])
        send_mail_mock.assert_not_called()

    def test_forgot_password_invalid_payload_returns_validation_error(self):
        response = self.client.post(
            self.url,
            data={"email": "not-an-email"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "invalid_data")
        self.assertIn("errors", response.data)


class ResetPasswordEndpointTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("reset-password")
        self.user = User.objects.create_user(
            email="reset@test.com",
            password="OldPass123",
        )

    def _valid_payload(self, new_password="NewPass123"):
        return {
            "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
            "token": PasswordResetTokenGenerator().make_token(self.user),
            "new_password": new_password,
        }

    def test_reset_password_happy_path(self):
        response = self.client.post(self.url, data=self._valid_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass123"))

    def test_reset_password_invalid_uid(self):
        payload = self._valid_payload()
        payload["uid"] = "invalid-uid"
        response = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("uid", response.data["errors"])

    def test_reset_password_invalid_token(self):
        payload = self._valid_payload()
        payload["token"] = "invalid-token"
        response = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("token", response.data["errors"])

    def test_reset_password_weak_password_rejected(self):
        payload = self._valid_payload(new_password="weakpass")
        response = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("new_password", response.data["errors"])

    def test_reset_password_missing_required_fields(self):
        response = self.client.post(self.url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("uid", response.data["errors"])
        self.assertIn("token", response.data["errors"])
        self.assertIn("new_password", response.data["errors"])


class TokenRefreshSessionExpiredTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("token-refresh")
        self.user = User.objects.create_user(
            email="refresh@test.com",
            password="Password@123",
        )

    def test_token_refresh_with_invalid_token_returns_session_expired(self):
        response = self.client.post(
            self.url,
            data={"refresh": "invalid-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "session_expired")

    def test_token_refresh_with_blacklisted_token_returns_session_expired(self):
        refresh = RefreshToken.for_user(self.user)
        refresh.blacklist()

        response = self.client.post(
            self.url,
            data={"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"], "session_expired")
        
        
@override_settings(MAX_ACTIVE_DEVICE_SESSIONS=4)
class DeviceSessionLimitTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="device-limit@test.com",
            password="StrongPass123!",
        )
        self.login_url = reverse("user-login")
        self.refresh_url = reverse("token-refresh")

    def _login_and_get_refresh(self) -> str:
        response = self.client.post(
            self.login_url,
            data={"email": self.user.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", response.data)
        return response.data["tokens"]["refresh"]

    def test_login_more_than_max_devices_revokes_oldest_session(self):
        refresh_tokens = [self._login_and_get_refresh() for _ in range(5)]

        oldest_refresh = refresh_tokens[0]
        newest_refresh = refresh_tokens[-1]

        oldest_response = self.client.post(
            self.refresh_url,
            data={"refresh": oldest_refresh},
            format="json",
        )
        self.assertEqual(oldest_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(oldest_response.data["error"], "session_expired")

        newest_response = self.client.post(
            self.refresh_url,
            data={"refresh": newest_refresh},
            format="json",
        )
        self.assertEqual(newest_response.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", newest_response.data)
        self.assertIn("access", newest_response.data["tokens"])


class LogoutAndAuthContractTests(APITestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="logout-contract@test.com",
            password="StrongPass123!",
        )
        login_response = self.client.post(
            reverse("user-login"),
            data={"email": self.user.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.access = login_response.data["tokens"]["access"]
        self.refresh = login_response.data["tokens"]["refresh"]

    def test_logout_blacklists_refresh_token_and_refresh_cannot_be_reused(self):
        logout_response = self.client.post(
            reverse("user-logout"),
            data={"refresh_token": self.refresh},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
        )
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
        self.assertTrue(logout_response.data["success"])

        refresh_response = self.client.post(
            reverse("token-refresh"),
            data={"refresh": self.refresh},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(refresh_response.data["error"], "session_expired")

    def test_notification_contract_includes_preference_only_metadata(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("user-notification"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["preference_only"], True)
        self.assertEqual(response.data["capabilities"]["notification_delivery"], "preference_only")
        self.assertEqual(response.data["data"]["preference_contract"], "preference_only")


