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
from rest_framework.exceptions import NotFound, ValidationError


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

        # Handle specific exceptions

        if isinstance(exc, NotFound):
            return Response(
                {
                    "error": "Resource not found",
                    "code": "not_found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if isinstance(exc, ValidationError):
            return Response(
                {
                    "error": "Validation error",
                    "details": exc.detail if hasattr(exc, "detail") else str(exc),
                    "code": "validation_error",
                },
                status=status.HTTP_400_BAD_REQUEST,
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
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
                "user": UserProfileSerializer(user).data,
                "timestamp": timezone.now().isoformat(),
            }
            return created_response(
                data=response_data, message="User registered successfully"
            )

        except Exception as e:
            logger.error(f"Registration failed: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred during registration. Please try again later.",
                code="registration_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )


class UserLoginView(ProductionApiView):
    """
    Custom login view that uses UserLoginSerializer
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]  # Apply rate limiting to login attempts

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


class UserLogoutView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnonRateThrottle]

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

            if str(token_user_id) != str(current_user_id):
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


# User Details such as username, email, is_active, ...etc


class UserView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return success_response(
            data=serializer.data, message="User profile retrieved successfully"
        )


class UserDeactivateView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        """
        Delete (deactivate) the user's account. This is a soft delete that sets is_active to False.
        Returns:
            - 200: Account deactivated successfully
            - 400: Invalid data
        """
        deactivate = request.data.get("deactivate", True)
        try:
            user = request.user
            user.is_active = deactivate
            user.save()
            logger.info(
                f"Account {'activated' if not deactivate else 'deactivated'} successfully for user: {user.email}"
            )
            return success_response(
                message=f"Account {'activated' if not deactivate else 'deactivated'} successfully"
            )
        except Exception as e:
            logger.error(f"Error updating account status: {str(e)}", exc_info=True)

            return error_response(
                message="An error occurred while updating the account status. Please try again.",
                code="account_status_update_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )


class ProfileDetailView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        """
        Retrieve user profile information

        Returns:
            - 200: Profile retrieved successfully
            - 404: Profile not found (though we create if missing)
        """

        try:
            profile, created = Profile.objects.get_or_create(user=request.user)
            if created:
                logger.info(f"Create New Profile for user: {request.user.email}")

            serializer = ProfileSerializer(profile)
            return success_response(
                data=serializer.data,
                message="Profile retrieved successfully",
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error retrieving profile: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred while retrieving the profile.",
                code="profile_retrieval_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )

    def put(self, request):
        """
        Update user profile (full update)

        Returns:
            - 200: Profile updated successfully
            - 400: Invalid update data
            - 404: Profile not found
        """

        try:
            profile = Profile.objects.get(user=request.user)
        except Profile.DoesNotExist:
            return error_response(
                message="Profile not found.",
                code="profile_not_found",
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProfileSerializer(profile, data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid profile data.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            serializer.save()
            logger.info(f"Profile updated successfully for user: {request.user.email}")
            return success_response(
                data=serializer.data,
                message="Profile updated successfully",
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error updating profile: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred while updating the profile.",
                code="profile_update_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )


class UserPersonalDetailsAPIView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get_object(self, user):
        try:
            return UserPersonalDetails.objects.get(user=user)
        except UserPersonalDetails.DoesNotExist:
            return None

    def get_queryset(self):
        return UserPersonalDetails.objects.filter(user=self.request.user)   

    def get(self, request):
        details = self.get_queryset().first()

        if details is None:
            return success_response(
                data={},   # or {} if frontend prefers
                message="Personal details not created yet.",
                status=status.HTTP_200_OK,
            )

        serializer = UserPersonalDetailsSerializer(details)

        return success_response(
            data=serializer.data,
            message="Personal details retrieved successfully",
            status=status.HTTP_200_OK,
        )



    def post(self, request):
        """
        Create personal details for the logged-in user
        """

        exsiting_user = self.get_object(request.user)

        if exsiting_user:
            logger.warning(
                f"Personal details already exist for user: {request.user.email}"
            )

            return error_response(
                message="Personal details already exist.",
                code="details_already_exist",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str("Personal details already exist.")],
            )

        serializer = UserPersonalDetailsSerializer(data=request.data)

        if not serializer.is_valid():
            return error_response(
                message="Invalid personal details data.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            serializer.save(user=request.user)
            logger.info(
                f"Personal details created successfully for user: {request.user.email}"
            )
            return success_response(
                data=serializer.data,
                message="Personal details created successfully",
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.error(f"Error creating personal details: {str(e)}", exc_info=True)

            return error_response(
                message="An error occurred while creating personal details.",
                code="details_creation_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )

    def put(self, request):
        """
        Full update of personal details
        """

        details = self.get_object(request.user)
        if details is None:
            return error_response(
                message="Personal details not found.",
                code="details_not_found",
                status=status.HTTP_404_NOT_FOUND,
                errors=[str("Personal details not found.")],
            )

        serializer = UserPersonalDetailsSerializer(details, data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid personal details data.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            serializer.save()
            logger.info(
                f"Personal details updated successfully for user: {request.user.email}"
            )

            return success_response(
                data=serializer.data,
                message="Personal details updated successfully",
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error updating personal details: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred while updating personal details.",
                code="details_update_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )

    def delete(self, request):
        """
        Delete personal details of the logged-in user
        """
        details = self.get_object(request.user)
        if details is None:
            return error_response(
                message="Personal details not found.",
                code="details_not_found",
                status=status.HTTP_404_NOT_FOUND,
                errors=[str("Personal details not found.")],
            )

        user_email = request.user.email
        details.delete()
        logger.info(f"Personal details deleted successfully for user: {user_email}")
        return success_response(
            message="Personal details deleted successfully",
            status=status.HTTP_204_NO_CONTENT,
        )


class NotificationDetailView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        try:
            notification, _ = NotificationSettings.objects.get_or_create(user=request.user)
            serializer = NotificationSettingsSerializer(notification)
            return success_response(
                data=serializer.data,
                message="Notification settings retrieved successfully",
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error retrieving notification settings: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred while retrieving notification settings.",
                code="notification_retrieval_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )

    def put(self, request):
        try:
            notification, _ = NotificationSettings.objects.get_or_create(user=request.user)
            serializer = NotificationSettingsSerializer(notification, data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid notification settings data.",
                    errors=serializer.errors,
                    code="invalid_data",
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Notification settings updated successfully",
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error updating notification settings: {str(e)}", exc_info=True)
            return error_response(
                message="An error occurred while updating notification settings.",
                code="notification_update_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )
