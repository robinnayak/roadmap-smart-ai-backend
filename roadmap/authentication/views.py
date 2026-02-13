"""
authentication/views.py
-----------------------
Views for user registration, authentication, profile management, and token operations.

"""

import logging
from django.utils import timezone
from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404


# Django REST Framework imports
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle


# DRF Simple JWT imports
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.views import TokenRefreshView

# Local imports
from .serializers import (
    UserRegisterSerializer,
    UserLoginSerializer,
    UserLogoutSerializer,
    UserProfileSerializer,
    ProfileSerializer,
    UserPersonalDetailsSerializer,
    NotificationSettingsSerializer,
)
from .models import Profile, NotificationSettings, UserPersonalDetails

# ApiResponse utility for consistent API responses
from .core.response import success_response, error_response, created_response

logger = logging.getLogger(__name__)



class ProductionApiView(APIView):
    """
    Base API view for production environment with enhanced logging and error handling.
    """

    throttle_classes = [UserRateThrottle]

    def handle_exception(self, exc):
        """
        Global exception handler for consistent error responses and logging in production.
        """

        logger.error(
            f"Exception occurred in {self.__class__.__name__}: {str(exc)}",
            exc_info=True,
        )

        # You can add custom exception handling here
        # For production, avoid exposing internal errors to clients. Instead, return a generic error message.
        if isinstance(exc, (TokenError, InvalidToken)):
            return Response(
                {
                    "error": "Token is invalid or expired",
                    "code": "token_not_valid",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return super().handle_exception(exc)


class UserRegistrationView(ProductionApiView):
    """
    Handle user registration. Accepts email, password, and optional profile data. Returns JWT tokens and user info on success.
    Rate limited to prevent abuse.

    """

    permission_classes = [AllowAny]
    throttle_classes = [
        AnonRateThrottle
    ]  # Only apply rate limiting to unauthenticated users (registration attempts)
    
    def get(self, request):
        return success_response(
            data={
                "message": "Welcome to the User Registration endpoint. Please POST your registration data to create an account.",
                "timestamp": timezone.now().isoformat(),
                "version": "1.0.0",
            },
            status=status.HTTP_200_OK,
            
        )
        

    def post(self, request):
        """
        Register a new user

        Request Body:
            email: string (required)
            username: string (optional)
            password: string (required)
            password2: string (required) - password confirmation

        Returns:
            - 201: User created successfully with tokens
            - 400: Invalid input data
            - 429: Too many requests (rate limited)
        """
        serializer = UserRegisterSerializer(data=request.data)

        if not serializer.is_valid():
            logger.warning(
                f"User registration failed due to invalid data: {serializer.errors}"
            )
            return error_response(
                message="Invalid registration data",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )
            
        try:
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            
            logger.info(f"User registered successfully: {user.email}")
            
            response_data = {
                "tokens":{
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
                "user": UserProfileSerializer(user).data,
                "timestamp": timezone.now().isoformat(),
            }
            return created_response(data=response_data, message="User registered successfully")
        
        except Exception as e:
            logger.error(f"Registration failed: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred during registration. Please try again later.",
                code="registration_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )
            


class UserLoginView(APIView):
    """
    Custom login view that uses UserLoginSerializer
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data.get("email")
            password = serializer.validated_data.get("password")

            # Authenticate user
            user = authenticate(request, email=email, password=password)

            if user is not None:
                if user.is_active:
                    # Generate tokens
                    refresh = RefreshToken.for_user(user)

                    response_data = {
                        "message": "Login successful",
                        "tokens": {
                            "access": str(refresh.access_token),
                            "refresh": str(refresh),
                        },
                        "user": UserProfileSerializer(user).data,
                    }
                    return Response(response_data, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {"error": "Account is not active"},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
            else:
                return Response(
                    {"error": "Invalid credentials"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UserLogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid logout data",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh_token = serializer.validated_data.get("refresh_token")
            if not refresh_token:
                return error_response(
                    message="Refresh token is required for logout",
                    code="refresh_token_required",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Simply validate the refresh token (no blacklisting)
            token = RefreshToken(refresh_token)

            # Verify the token is valid and belongs to the authenticated user
            token_user_id = token.payload.get("user_id")
            current_user_id = request.user.id

            print("==" * 70)
            print(f"Token user ID: {token_user_id}, Current user ID: {current_user_id}")
            print("==" * 70)
            
            if (str(token_user_id) != str(current_user_id)):
                return error_response(
                    message="Token does not belong to the authenticated user",
                    code="invalid_token_user",
                    status=status.HTTP_403_FORBIDDEN,
                )
            token.blacklist()  # Blacklist the refresh token to prevent reuse
            return success_response(message="Logout successful")

        except Exception as e:
            return error_response(
                message="An error occurred during logout. Please try again.",
                code="logout_error",
                status=status.HTTP_400_BAD_REQUEST,
            )




class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            # Optionally, you can customize the response format
            return Response(
                {
                    "tokens": {
                        "access": response.data.get("access"),
                    },
                    "message": "Token refreshed successfully",
                },
                status=status.HTTP_200_OK,
            )
        except (InvalidToken, TokenError):
            return Response(
                {
                    "error": "Token is invalid or expired",
                    "code": "token_not_valid",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )


class ProfileDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get or create profile
        profile, created = Profile.objects.get_or_create(user=request.user)
        print(f"profile created: {created}")

        # For GET requests, just serialize the instance
        serializer = ProfileSerializer(profile)
        print(f"serializer data: {serializer.data}")
        print("==" * 70)

        # Return the serialized data
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        profile, created = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserPersonalDetailsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, user):
        """
        Helper method to get the user's personal details
        """
        try:
            return get_object_or_404(UserPersonalDetails, user=user)
        except UserPersonalDetails.DoesNotExist:
            return None

    # ✅ CREATE (POST)
    def post(self, request):
        """
        Create personal details for the logged-in user
        """
        if UserPersonalDetails.objects.filter(user=request.user).exists():
            return Response(
                {"detail": "Personal details already exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserPersonalDetailsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # 👀 READ (GET)
    def get(self, request):
        """
        Retrieve personal details of the logged-in user
        """
        details = self.get_object(request.user)
        serializer = UserPersonalDetailsSerializer(details)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ✏️ UPDATE (PUT / PATCH)
    def put(self, request):
        """
        Full update of personal details
        """
        details = self.get_object(request.user)
        serializer = UserPersonalDetailsSerializer(details, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # def patch(self, request):
    #     """
    #     Partial update of personal details
    #     """
    #     details = self.get_object(request.user)
    #     serializer = UserPersonalDetailsSerializer(
    #         details,
    #         data=request.data,
    #         partial=True
    #     )

    #     if serializer.is_valid():
    #         serializer.save()
    #         return Response(serializer.data)

    #     return Response(
    #         serializer.errors,
    #         status=status.HTTP_400_BAD_REQUEST
    #     )

    # ❌ DELETE
    def delete(self, request):
        """
        Delete personal details of the logged-in user
        """
        details = self.get_object(request.user)
        details.delete()
        return Response(
            {"detail": "Personal details deleted successfully."},
            status=status.HTTP_204_NO_CONTENT,
        )


class NotificationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        print("==" * 70)
        print("user", request.user)

        # Get or create profile
        notification, created = NotificationSettings.objects.get_or_create(
            user=request.user
        )
        print(f"profile: {notification}, created: {created}")

        # For GET requests, just serialize the instance
        serializer = NotificationSettingsSerializer(notification)
        print(f"serializer data: {serializer.data}")
        print("==" * 70)
        # Return the serialized data
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        profile, created = NotificationSettings.objects.get_or_create(user=request.user)
        serializer = NotificationSettingsSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
