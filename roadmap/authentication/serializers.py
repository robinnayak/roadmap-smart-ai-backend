from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser



class UserRegisterSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    
    class Meta:
        model = CustomUser
        fields = ('email','username' ,'password', 'password2')
        extra_kwargs = {
            'password': {'write_only': True}
        }
        
    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        validate_password(attrs['password'])
        return attrs
    
    def create(self, validated_data):
        username = validated_data.pop('username', None)
        if not username:
            username = validated_data['email'].split('@')[0]
            validated_data['username'] = username
        user = CustomUser.objects.create(
            email=validated_data['email'],
            username=validated_data['username']
        )
        user.set_password(validated_data['password'])
        user.save()
        return super().create(validated_data)
    

class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    
    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        
        if email and password:
            user = CustomUser.objects.filter(email=email).first()
            if user:
                if not user.check_password(password):
                    raise serializers.ValidationError('Invalid password')
            else:
                raise serializers.ValidationError('User not found')
        return attrs

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ('id', 'email', 'username', 'date_joined')
    
    
    
    
    