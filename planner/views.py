from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteSerializer


class RouteView(APIView):

    def post(self, request):
        serializer = RouteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start = serializer.validated_data["start"]
        finish = serializer.validated_data["finish"]

        return Response(
            {
                "start": start,
                "finish": finish,
            }
        )
