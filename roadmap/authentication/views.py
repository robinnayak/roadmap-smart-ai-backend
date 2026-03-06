"""
authentication/views.py
-----------------------
Views for user registration, authentication, profile management, and token operations.

"""

import logging
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.conf import settings
from django.core.mail import send_mail
from django.core import signing
from django.utils.encoding import force_bytes
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
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
    UserReactivateSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,
)
from .models import Profile, NotificationSettings, UserPersonalDetails

# ApiResponse utility for consistent API responses
from .core.response import success_response, error_response, created_response

logger = logging.getLogger(__name__)
User = get_user_model()
REACTIVATION_TOKEN_SALT = "authentication.reactivation"
REACTIVATION_TOKEN_MAX_AGE_SECONDS = getattr(
    settings, "REACTIVATION_TOKEN_MAX_AGE_SECONDS", 900
)


def _build_reactivation_token(user):
    signer = signing.TimestampSigner(salt=REACTIVATION_TOKEN_SALT)
    payload = f"{user.id}:{user.email.lower()}"
    return signer.sign(payload)


def _build_reactivation_path_payload(reactivation_token):
    return {
        "reactivation_token": reactivation_token,
        "expires_in_seconds": REACTIVATION_TOKEN_MAX_AGE_SECONDS,
        "reactivate_endpoint": "/auth/user-reactivate/",
    }


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

        if not serializer.is_valid():
            return error_response(
                message="Invalid login payload.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]
        if not user.is_active:
            reactivation_token = _build_reactivation_token(user)
            return error_response(
                message=(
                    "This account is deactivated. Reactivate your account to continue."
                ),
                code="account_deactivated",
                status=status.HTTP_403_FORBIDDEN,
                extra={"reactivation": _build_reactivation_path_payload(reactivation_token)},
            )

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


class ForgotPasswordView(ProductionApiView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid forgot-password payload.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()

        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = PasswordResetTokenGenerator().make_token(user)
            reset_base_url = getattr(settings, "PASSWORD_RESET_URL", "").strip()
            if reset_base_url:
                separator = "&" if "?" in reset_base_url else "?"
                reset_link = f"{reset_base_url}{separator}uid={uid}&token={token}"
                try:
                    send_mail(
                        subject="Reset your password",
                        message=(
                            "You requested a password reset.\n\n"
                            f"Use this link to reset your password:\n{reset_link}\n\n"
                            "If you did not request this, you can ignore this message."
                        ),
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                        recipient_list=[user.email],
                        fail_silently=True,
                    )
                except Exception:
                    logger.exception(
                        "Forgot-password email dispatch failed for user %s", user.id
                    )

        return success_response(
            message=(
                "If an account exists for this email, a password reset link has been sent."
            ),
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(ProductionApiView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid reset-password payload.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except Exception:
            return error_response(
                message="Invalid reset token or user.",
                errors={"uid": ["Invalid uid."]},
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_generator = PasswordResetTokenGenerator()
        if not token_generator.check_token(user, token):
            return error_response(
                message="Invalid reset token or user.",
                errors={"token": ["Invalid or expired token."]},
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        return success_response(
            message="Password reset successful.",
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(ProductionApiView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            error_code = serializer.errors.get("current_password")
            return error_response(
                message=(
                    "current password not matched."
                    if error_code and "current password not matched." in error_code
                    else "Invalid password change data."
                ),
                errors=serializer.errors,
                code=(
                    "invalid_current_password"
                    if error_code and "current password not matched." in error_code
                    else "invalid_data"
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        logger.info("Password changed successfully for user: %s", request.user.email)
        return success_response(
            message="Password updated successfully.",
            status=status.HTTP_200_OK,
        )


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
                    "error": "session_expired",
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
        try:
            user = request.user
            if not user.is_active:
                return error_response(
                    message="Account is already deactivated.",
                    code="already_deactivated",
                    status=status.HTTP_409_CONFLICT,
                )

            user.is_active = False
            user.save(update_fields=["is_active"])
            logger.info("Account deactivated successfully for user: %s", user.email)
            return success_response(
                message="Account deactivated successfully. You can reactivate it at any time."
            )
        except Exception as e:
            logger.error(f"Error updating account status: {str(e)}", exc_info=True)

            return error_response(
                message="An error occurred while updating the account status. Please try again.",
                code="account_status_update_error",
                status=status.HTTP_400_BAD_REQUEST,
                errors=[str(e)],
            )


class UserReactivateView(ProductionApiView):
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = UserReactivateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid reactivation payload.",
                errors=serializer.errors,
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = serializer.validated_data["reactivation_token"]
        signer = signing.TimestampSigner(salt=REACTIVATION_TOKEN_SALT)
        try:
            payload = signer.unsign(token, max_age=REACTIVATION_TOKEN_MAX_AGE_SECONDS)
        except signing.SignatureExpired:
            return error_response(
                message="Reactivation token is invalid or expired.",
                code="invalid_or_expired_token",
                status=status.HTTP_400_BAD_REQUEST,
                errors={"reactivation_token": ["Token has expired."]},
            )
        except signing.BadSignature:
            return error_response(
                message="Reactivation token is invalid or expired.",
                code="invalid_or_expired_token",
                status=status.HTTP_400_BAD_REQUEST,
                errors={"reactivation_token": ["Token is invalid."]},
            )

        try:
            user_id, email = payload.split(":", 1)
            user = User.objects.get(id=user_id, email__iexact=email)
        except (ValueError, User.DoesNotExist):
            return error_response(
                message="Unauthorized reactivation attempt.",
                code="unauthorized_reactivation_attempt",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.is_active:
            return error_response(
                message="Account is already active.",
                code="already_active",
                status=status.HTTP_409_CONFLICT,
            )

        user.is_active = True
        user.save(update_fields=["is_active"])
        refresh = RefreshToken.for_user(user)
        return success_response(
            message="Account reactivated successfully.",
            data={
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
                "user": UserProfileSerializer(user).data,
            },
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
        if any(
            field in request.data
            for field in ("current_password", "new_password", "confirm_password")
        ):
            return error_response(
                message="Use /auth/change-password/ endpoint for password updates.",
                errors={
                    "non_field_errors": [
                        "Password updates are not supported on /auth/profile/."
                    ]
                },
                code="invalid_data",
                status=status.HTTP_400_BAD_REQUEST,
            )

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
