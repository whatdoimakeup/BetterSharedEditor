"""
URL configuration for the core app.
"""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Room CRUD
    path("rooms/", views.RoomListCreateView.as_view(), name="room-list-create"),
    path("rooms/<int:room_id>/", views.RoomDetailView.as_view(), name="room-detail"),
    path(
        "rooms/<int:room_id>/state/",
        views.RoomStateView.as_view(),
        name="room-state",
    ),
    path(
        "rooms/<int:room_id>/upload-update/",
        views.RoomUploadUpdateView.as_view(),
        name="room-upload-update",
    ),
    # Centrifugo RPC proxy
    path("centrifugo/rpc/", views.centrifugo_rpc, name="centrifugo-rpc"),
]
