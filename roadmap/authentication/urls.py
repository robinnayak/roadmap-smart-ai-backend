from django.urls import path
from .views import (
    UserRegistrationView,
    UserLoginView,
    UserLogoutView,
    # UserProfileView,
    CustomTokenRefreshView,
    ProfileDetailView,
    NotificationDetailView,
    UserPersonalDetailsAPIView,
    UserDeactivateView,
    UserReactivateView,
    UserView,
    ForgotPasswordView,
    ResetPasswordView,
    ChangePasswordView,
    GoogleAuthView,
    MagicLinkRequestView,
    MagicLinkVerifyView,
)

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="user-register"),
    path("login/", UserLoginView.as_view(), name="user-login"),
    path("google/", GoogleAuthView.as_view(), name="google-auth"),
    path("magic-link/request/", MagicLinkRequestView.as_view(), name="magic-link-request"),
    path("magic-link/verify/", MagicLinkVerifyView.as_view(), name="magic-link-verify"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("logout/", UserLogoutView.as_view(), name="user-logout"),
    path("user-deactivate/", UserDeactivateView.as_view(), name="user-profile-deactivate"),
    path("user-reactivate/", UserReactivateView.as_view(), name="user-profile-reactivate"),
    path("profile/", ProfileDetailView.as_view(), name="user-profile"),
    path("personal-details/", UserPersonalDetailsAPIView.as_view(), name="user-personal-details"),
    path("notification/", NotificationDetailView.as_view(), name="user-notification"),
    path("user/", UserView.as_view(), name="user-view"),
    # path("profile/", UserProfileView.as_view(), name="user-profile"),
    # path
    
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token-refresh"),
]
