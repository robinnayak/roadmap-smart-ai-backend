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
    UserView
)

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="user-register"),
    path("login/", UserLoginView.as_view(), name="user-login"),
    path("logout/", UserLogoutView.as_view(), name="user-logout"),
    path("user-deactivate/", UserDeactivateView.as_view(), name="user-profile-deactivate"),
    path("profile/", ProfileDetailView.as_view(), name="user-profile"),
    path("personal-details/", UserPersonalDetailsAPIView.as_view(), name="user-personal-details"),
    path("notification/", NotificationDetailView.as_view(), name="user-notification"),
    path("user/", UserView.as_view(), name="user-view"),
    # path("profile/", UserProfileView.as_view(), name="user-profile"),
    # path
    
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token-refresh"),
]
