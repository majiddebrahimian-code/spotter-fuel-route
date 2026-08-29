from rest_framework import serializers


class RouteSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )

    finish = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )
