from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteSerializer
from .services.geocoding import geocode
from .services.routing import get_route


class RouteView(APIView):

    def post(self, request):
        serializer = RouteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start_name = serializer.validated_data["start"]
        finish_name = serializer.validated_data["finish"]

        start = geocode(start_name)
        finish = geocode(finish_name)

        if not start or not finish:
            return Response(
                {"error": "Could not find one of the locations."},
                status=400,
            )

        route = get_route(start, finish)

        if not route:
            return Response(
                {"error": "Could not calculate the route."},
                status=400,
            )

        return Response(
            {
                "start": start,
                "finish": finish,
                "route": route,
            }
        )
