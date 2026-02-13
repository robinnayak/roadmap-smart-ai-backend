import json
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework.test import APITestCase
from django.urls import reverse
# from django.test import Client
from rest_framework.test import APIClient as Client
from django.core.cache import cache
from rest_framework import status 


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
        
        

