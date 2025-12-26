# authentication/tests.py

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from .models import CustomUser


class AuthenticationAPITests(APITestCase):
    def setUp(self):
        self.test_user = CustomUser.objects.create_user(
            email="existing@example.com",
            username="existinguser",
            password="StrongPass123!"
        )

        self.register_url = reverse("user-register")
        self.login_url = reverse("user-login")
        self.logout_url = reverse("user-logout")
        self.profile_url = reverse("user-profile")
        self.refresh_url = reverse("token-refresh")

    # Registration Tests – All good as-is!
    def test_register_success(self):
        data = {
            "email": "newuser@example.com",
            "username": "newuser",
            "password": "StrongPass123!",
            "password2": "StrongPass123!"
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CustomUser.objects.filter(email="newuser@example.com").exists())
        self.assertIn("tokens", response.data)
        self.assertIn("user", response.data)

    def test_register_duplicate_email(self):
        data = {
            "email": "existing@example.com",
            "username": "newone",
            "password": "StrongPass123!",
            "password2": "StrongPass123!"
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertIn("already exists", str(response.data["email"][0]))

    def test_register_password_mismatch(self):
        data = {
            "email": "test@example.com",
            "username": "testuser",
            "password": "StrongPass123!",
            "password2": "Different123!"
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_register_weak_password(self):
        data = {
            "email": "weak@example.com",
            "username": "weakuser",
            "password": "123",
            "password2": "123"
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_register_auto_generate_username(self):
        data = {
            "email": "auto@example.com",
            "password": "StrongPass123!",
            "password2": "StrongPass123!"
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = CustomUser.objects.get(email="auto@example.com")
        self.assertTrue(user.username.startswith("auto"))

    # Login Tests – Fixed to match your custom response
    def test_login_success(self):
        data = {
            "email": "existing@example.com",
            "password": "StrongPass123!"
        }
        response = self.client.post(self.login_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Login successful")
        self.assertIn("tokens", response.data)
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])
        self.assertIn("refresh", response.data)  # top-level refresh

    def test_login_wrong_credentials(self):
        data = {
            "email": "existing@example.com",
            "password": "wrongpass"
        }
        response = self.client.post(self.login_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("message", response.data)
        self.assertEqual(response.data["message"], "Invalid credentials")

    # Profile Tests – Perfect
    def test_profile_access_authenticated(self):
        refresh = RefreshToken.for_user(self.test_user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get(self.profile_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.test_user.email)

    def test_profile_access_unauthenticated(self):
        self.client.credentials()
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # Token Refresh – Good
    def test_token_refresh_success(self):
        refresh = RefreshToken.for_user(self.test_user)
        refresh_token = str(refresh)

        response = self.client.post(
            self.refresh_url,
            {"refresh": refresh_token},
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    # Logout Test – Fixed key name
    def test_logout_success(self):
        refresh = RefreshToken.for_user(self.test_user)
        refresh_token = str(refresh)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        response = self.client.post(
            self.logout_url,
            {"refresh_token": refresh_token},  # ← Changed to "refresh_token"
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Successfully logged out.")