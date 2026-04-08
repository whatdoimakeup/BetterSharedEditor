from django.contrib import admin, messages
from django.db import DatabaseError

from .models import Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at", "updated_at")
    search_fields = ("id", "name")
    readonly_fields = ("id", "created_at", "updated_at", "yjs_state", "content")
    ordering = ("-updated_at", "-id")
    show_full_result_count = False

    def get_queryset(self, request):
        queryset = super().get_queryset(request).using("tarantool")
        try:
            queryset.exists()
            return queryset
        except DatabaseError as exc:
            self.message_user(request, f"Tarantool is unavailable: {exc}", level=messages.ERROR)
            return self.model.objects.none()
