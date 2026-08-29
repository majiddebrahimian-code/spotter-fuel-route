from django.contrib import admin
from django.urls import include, path

from planner.views import RouteMapView

urlpatterns = [
    path(
        "admin/",
        admin.site.urls,
    ),
    path(
        "api/routes/",
        include("planner.urls"),
    ),
    path(
        "map/",
        RouteMapView.as_view(),
        name="route-map",
    ),
]
