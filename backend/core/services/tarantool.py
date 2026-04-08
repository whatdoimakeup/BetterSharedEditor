"""Tarantool service backed by the Django ORM."""

import logging
from typing import Any

from django.utils import timezone

from core.models import Room

logger = logging.getLogger(__name__)


class TarantoolClient:
    """High-level room operations executed through the Tarantool Django backend."""

    @staticmethod
    def _now() -> str:
        return timezone.now().isoformat()

    def ping(self) -> bool:
        """Check if the Tarantool ORM backend is reachable."""
        try:
            Room.objects.using("tarantool").exists()
            return True
        except Exception as e:
            logger.error("Tarantool ORM ping failed: %s", e)
            return False

    def insert_room(self, room_id: int, name: str) -> dict[str, Any]:
        """Create a new room in Tarantool via Django ORM."""
        now = self._now()
        room = Room(
            id=room_id,
            name=name,
            created_at=now,
            yjs_state=None,
            content="",
            updated_at=now,
        )
        room.save(using="tarantool", force_insert=True)
        return self._room_to_dict(room)

    def get_room(self, room_id: int) -> dict[str, Any] | None:
        """Get a room by ID."""
        room = Room.objects.using("tarantool").filter(pk=room_id).first()
        return self._room_to_dict(room) if room else None

    def get_room_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a room by name."""
        room = Room.objects.using("tarantool").filter(name=name).order_by("id").first()
        return self._room_to_dict(room) if room else None

    def list_rooms(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List rooms using Django ORM queries."""
        rooms = Room.objects.using("tarantool").all().order_by("-updated_at", "-id")[offset : offset + limit]
        return [self._room_to_dict(room) for room in rooms]

    def update_room_content(self, room_id: int, content: str, yjs_state: bytes | None = None) -> dict[str, Any] | None:
        """Update room content preview and optionally Yjs state."""
        room = Room.objects.using("tarantool").filter(pk=room_id).first()
        if not room:
            return None

        room.content = (content or "")[:250]
        if yjs_state is not None:
            room.yjs_state = yjs_state
        room.updated_at = self._now()
        room.save(using="tarantool")
        return self._room_to_dict(room)

    def update_room_yjs_state(self, room_id: int, yjs_state: bytes) -> dict[str, Any] | None:
        """Update only the Yjs state of a room."""
        room = Room.objects.using("tarantool").filter(pk=room_id).first()
        if not room:
            return None

        room.yjs_state = yjs_state
        room.updated_at = self._now()
        room.save(using="tarantool")
        return self._room_to_dict(room)

    def touch_room(self, room_id: int) -> dict[str, Any] | None:
        """Update room metadata timestamp while keeping the saved content preview."""
        room = Room.objects.using("tarantool").filter(pk=room_id).first()
        if not room:
            return None

        room.updated_at = self._now()
        room.save(using="tarantool")
        return self._room_to_dict(room)

    def delete_room(self, room_id: int) -> bool:
        """Delete a room."""
        deleted_count, _ = Room.objects.using("tarantool").filter(pk=room_id).delete()
        return deleted_count > 0

    def get_next_id(self) -> int:
        """Get the next available room ID."""
        last_room = Room.objects.using("tarantool").order_by("-id").only("id").first()
        return (last_room.id if last_room else 0) + 1

    @staticmethod
    def _room_to_dict(room: Room) -> dict[str, Any]:
        """Convert a room model instance to the API dictionary shape."""
        return {
            "id": room.id,
            "name": room.name,
            "created_at": room.created_at,
            "yjs_state": room.yjs_state,
            "content": room.content or "",
            "updated_at": room.updated_at,
        }


tarantool_client = TarantoolClient()
