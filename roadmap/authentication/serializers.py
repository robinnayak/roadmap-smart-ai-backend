# authentication/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser

class UserRegisterSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = CustomUser
        fields = ('email', 'username', 'password', 'password2')
        extra_kwargs = {
            'password': {'write_only': True},
            'username': {'required': False, 'allow_blank': True},  # Allow optional
        }

    def validate_email(self, value):
        if CustomUser.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})

        validate_password(attrs['password'])
        return attrs

    def create(self, validated_data):
        print("="*40)
        print(validated_data)
        print("="*40)   
        # Remove password2 before creating
        validated_data.pop('password2', None)

        # Handle username (optional)
        username = validated_data['email'].split('@')[0]
        # Ensure unique username
        base = username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1

        # Create user
        user = CustomUser.objects.create(
            email=validated_data['email'],
            username=username
            # **validated_data  # in case you add more fields later
        )
        user.set_password(validated_data['password'])
        user.save()

        return user  # ← DO NOT call super().create() — we already created it!
    
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
                    raise serializers.ValidationError('Invalid password')
            else:
                raise serializers.ValidationError('User not found')
                
        else:
            raise serializers.ValidationError('Email and password are required')
        
        data['user'] = user
        return data

class UserLogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(required=True)


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()   