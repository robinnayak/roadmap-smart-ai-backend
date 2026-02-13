# authentication/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser, Profile, NotificationSettings, UserPersonalDetails
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()

class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        validators=[validate_password],
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )

    class Meta:
        model = User
        fields = ('email', 'username', 'password', 'password2')
        extra_kwargs = {
            'username': {'required': False, 'allow_blank': True},
            'email': {'required': True},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists.",
                code="email_taken"
            )
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password2'):
            raise serializers.ValidationError(
                {"password": "The two password fields didn't match."},
                code="password_mismatch"
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Remove non-model fields
        password = validated_data.pop('password')
        validated_data.pop('password2', None)  # safe, in case it's still there

        email = validated_data.pop('email')     # required field → must exist
        username = validated_data.pop('username', None)

        # Auto-generate username if not provided
        if not username:
            # Make base more username-friendly
            base = email.split('@')[0].lower()
            base = ''.join(c for c in base if c.isalnum() or c in '_-')  # safer
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}{counter}"
                counter += 1

        # Create the user using the proper manager method
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,           # create_user calls set_password internally
            **validated_data             # forward any extra validated fields
        )

        # Optional: create related models here or via signals
        # Profile.objects.create(user=user)

        return user


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ('email', 'username')

class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, data):
        email = data.get('email')
        password = data.get('password') 
        
        if email and password:
            user = CustomUser.objects.filter(email=email).first()   
            if user:
                if not user.check_password(password):
                    raise serializers.ValidationError(
                        {'password': 'The password you entered is incorrect. Please try again.'},
                        code='invalid_password'
                    )
            else:
                raise serializers.ValidationError(
                    {'email': 'No account was found with this email address. Please sign up first.'},
                    code='user_not_found'
                )
                
        else:
            raise serializers.ValidationError(
                'Both "email" and "password" are required.',
                code='missing_fields'
            )
        
        data['user'] = user
        return data

class UserLogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()   


#Profile Prefer Email and Username as read-only fields since they are tied to the user model and should not be changed through the profile endpoint. If you want to allow updates, you can remove the read_only=True and handle the updates in the view.
class ProfileSerializer(serializers.ModelSerializer):
    # Make these fields read-only if you don't want them to be updated
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = Profile
        fields = [
            'id', 'username', 'email', 'bio', 'avatar', 'timezone', 
            'subscription_tier', 'total_points', 
            'current_level', 'preferred_language', 'theme'
        ]
        
class UserPersonalDetailsSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = UserPersonalDetails
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')

class NotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSettings
        fields = (
            'id',
            'notifications_enabled',
            'routine_remainders',
            'streak_warnings',
            'personalize_assistant',
            'push_notifications',
            'email_notifications',
        )
        

