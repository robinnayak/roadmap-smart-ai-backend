from rest_framework import serializers


class AssistantMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=1000, trim_whitespace=True)
    mode = serializers.ChoiceField(choices=("chat", "voice"), required=False, default="chat")

