from rest_framework import serializers

from .models import UserRitualProfile


class ToneSerializer(serializers.Serializer):
    tone = serializers.ChoiceField(choices=[choice[0] for choice in UserRitualProfile.TONE_CHOICES])


class MorningEnergySerializer(serializers.Serializer):
    energy = serializers.ChoiceField(choices=["sleepy", "neutral", "energized", "fired"])


class NightReflectionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["done", "partial", "missed", "strong", "okay", "rough"])


class NightIntentSerializer(serializers.Serializer):
    task = serializers.CharField(max_length=500)
    alarm_time = serializers.TimeField(input_formats=["%H:%M", "%H:%M:%S"])


class NightCloseSerializer(serializers.Serializer):
    alarm_time = serializers.TimeField(input_formats=["%H:%M", "%H:%M:%S"])
    mood = serializers.ChoiceField(choices=["strong", "okay", "rough"])


class AlarmTimeSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["morning", "night"])
    time = serializers.TimeField(input_formats=["%H:%M", "%H:%M:%S"])


class SnoozeCountSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)