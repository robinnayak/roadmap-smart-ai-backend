# authentication/views.py

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate

from .serializers import (
    UserRegisterSerializer, UserLoginSerializer,
    UserLogoutSerializer, UserProfileSerializer,
    TokenRefreshSerializer
)
from .models import CustomUser


class UserRegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)

            response_data = {
                "message": "User registered successfully",
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
                "user": UserProfileSerializer(user).data,
            }
            return Response(response_data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(APIView):
    """
    Custom login view that uses UserLoginSerializer
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        
        if serializer.is_valid():
            email = serializer.validated_data.get('email')
            password = serializer.validated_data.get('password')
            
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
                        status=status.HTTP_401_UNAUTHORIZED
                    )
            else:
                return Response(
                    {"error": "Invalid credentials"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UserLogoutSerializer(data=request.data)
        print(serializer)
        print("="*40)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            print("==" * 40)
            refresh_token = serializer.validated_data.get("refresh_token")
            print("refresh_token",refresh_token)
            print("==" * 40)
            
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Simply validate the refresh token (no blacklisting)
            token = RefreshToken(refresh_token)
            print("==" * 40)
            print("token",token)
            print("==" * 40)

            
            # Verify the token is valid and belongs to the authenticated user
            token_user_id = token.payload.get('user_id')
            current_user_id = request.user.id
            print("==" * 40)
            print("token_user_id",token_user_id)
            print("current_user_id",current_user_id)
            print("==" * 40)

            
            return Response(
                {"message": "Successfully logged out. Client should discard tokens."},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response(
                {"error": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    
    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            # Optionally, you can customize the response format
            return Response({
                "tokens": {
                    "access": response.data.get("access"),
                },
                "message": "Token refreshed successfully"
            }, status=status.HTTP_200_OK)
        except (InvalidToken, TokenError):
            return Response(
                {
                    "error": "Token is invalid or expired",
                    "code": "token_not_valid",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )


# Optional: Keep this if you want both login methods
# class CustomTokenObtainPairView(TokenObtainPairView):
#     """
#     Alternative login using SimpleJWT's built-in logic with email
#     """
#     permission_classes = [AllowAny]
#     serializer_class = CustomTokenObtainPairSerializer
    
#     def post(self, request, *args, **kwargs):
#         response = super().post(request, *args, **kwargs)
        
#         if response.status_code == 200:
#             # Customize the response format
#             response.data = {
#                 "message": "Login successful",
#                 "tokens": {
#                     "access": response.data.get("access"),
#                     "refresh": response.data.get("refresh"),
#                 },
#                 "user": UserProfileSerializer(
#                     CustomUser.objects.get(email=request.data.get('email'))
#                 ).data,
#             }
        
#         return response