import requests

from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from planner.serializers import RouteSerializer
from planner.services.optimizer import NoFeasibleFuelPlan
from planner.services.route_planner import (
    LocationNotFoundError,
    RouteUnavailableError,
    plan_route,
)


class RouteMapView(TemplateView):
    template_name = "planner/map.html"


class RouteView(APIView):
    def post(self, request):
        serializer = RouteSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        start = serializer.validated_data["start"]

        finish = serializer.validated_data["finish"]

        try:
            result = plan_route(
                start_location=start,
                finish_location=finish,
            )

            return Response(
                result,
                status=status.HTTP_200_OK,
            )

        except LocationNotFoundError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except NoFeasibleFuelPlan as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        except RouteUnavailableError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        except requests.RequestException:
            return Response(
                {"error": ("External mapping service " "is temporarily unavailable.")},
                status=status.HTTP_502_BAD_GATEWAY,
            )
