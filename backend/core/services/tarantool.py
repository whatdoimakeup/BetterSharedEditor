"""
Tarantool database client service.

Provides connection pooling and high-level operations for room data storage.
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import tarantool
from django.conf import settings

logger = logging.getLogger(__name__)

# Space name constant
ROOMS_SPACE = "rooms"


def _retry_on_connection_error(func):
    """Decorator to retry Tarantool operations once on connection errors."""
    def wrapper(self, *args, **kwargs):
        max_retries = 2
        for attempt in range(max_retries):
            try:
                return func(self, *args, **kwargs)
            except (tarantool.Error, Exception) as e:
                if attempt < max_retries - 1:
                    # Msgpack or connection error — reconnect and retry
                    logger.warning(
                        "Tarantool request failed (attempt %d/%d): %s. Reconnecting...",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                    )
                    self._reconnect()
                else:
                    logger.error("Tarantool request failed after %d attempts: %s", max_retries, e)
                    raise
    return wrapper



class TarantoolClient:
    """Singleton-like Tarantool client with connection management."""

    _instance = None
    _connection = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_connection(self) -> tarantool.Connection:
        """Get or create Tarantool connection, with reconnect on error."""
        if self._connection is None:
            self._reconnect()
        else:
            # Check if connection is still alive
            try:
                self._connection.ping()
            except Exception as e:
                logger.warning("Tarantool connection lost (%s), reconnecting...", e)
                self._reconnect()
        return self._connection

    def _reconnect(self) -> None:
        """Reconnect to Tarantool."""
        self._connection = None
        try:
            self._connection = tarantool.connect(
                host=settings.TARANTOOL_HOST,
                port=settings.TARANTOOL_PORT,
                user=settings.TARANTOOL_USER,
                password=settings.TARANTOOL_PASSWORD,
            )
            logger.info(
                "Connected to Tarantool at %s:%d",
                settings.TARANTOOL_HOST,
                settings.TARANTOOL_PORT,
            )
        except Exception as e:
            logger.error("Failed to connect to Tarantool: %s", e)
            self._connection = None
            raise

    def ping(self) -> bool:
        """Check if Tarantool connection is alive."""
        try:
            conn = self._get_connection()
            result = conn.ping()
            return result.return_code == 0
        except Exception as e:
            logger.error("Tarantool ping failed: %s", e)
            return False

    @_retry_on_connection_error
    def insert_room(self, room_id: int, name: str) -> dict[str, Any]:
        """Create a new room in Tarantool."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()
        result = conn.insert(
            ROOMS_SPACE,
            [room_id, name, now, None, "", now],
        )
        if result.data:
            return self._row_to_dict(result.data[0])
        raise RuntimeError("Failed to insert room")

    @_retry_on_connection_error
    def get_room(self, room_id: int) -> dict[str, Any] | None:
        """Get a room by ID."""
        conn = self._get_connection()
        result = conn.select(ROOMS_SPACE, room_id)
        if result.data:
            return self._row_to_dict(result.data[0])
        return None

    @_retry_on_connection_error
    def get_room_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a room by name using secondary index."""
        conn = self._get_connection()
        result = conn.select(ROOMS_SPACE, name, index="name")
        if result.data:
            return self._row_to_dict(result.data[0])
        return None

    @_retry_on_connection_error
    def list_rooms(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List all rooms (iterates over space)."""
        conn = self._get_connection()
        # Select all with iterator
        result = conn.select(ROOMS_SPACE, offset=offset, limit=limit)
        return [self._row_to_dict(row) for row in result.data]

    @_retry_on_connection_error
    def update_room_content(
        self, room_id: int, content: str, yjs_state: bytes | None = None
    ) -> dict[str, Any] | None:
        """Update room content and optionally Yjs state."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()

        # Get current room first
        room = self.get_room(room_id)
        if not room:
            return None

        # Update via replace
        conn.replace(
            ROOMS_SPACE,
            [
                room_id,
                room["name"],
                room["created_at"],
                yjs_state if yjs_state is not None else room.get("yjs_state"),
                content,
                now,
            ],
        )
        return self.get_room(room_id)

    @_retry_on_connection_error
    def update_room_yjs_state(self, room_id: int, yjs_state: bytes) -> dict[str, Any] | None:
        """Update only the Yjs state of a room."""
        conn = self._get_connection()
        now = datetime.now(timezone.utc).isoformat()

        room = self.get_room(room_id)
        if not room:
            return None

        conn.replace(
            ROOMS_SPACE,
            [
                room_id,
                room["name"],
                room["created_at"],
                yjs_state,
                room.get("content") or "",
                now,
            ],
        )
        return self.get_room(room_id)

    @_retry_on_connection_error
    def delete_room(self, room_id: int) -> bool:
        """Delete a room."""
        conn = self._get_connection()
        result = conn.delete(ROOMS_SPACE, room_id)
        return result.return_code == 0

    @_retry_on_connection_error
    def get_next_id(self) -> int:
        """Get next available room ID (simple auto-increment simulation)."""
        conn = self._get_connection()
        # Select all and find max ID
        result = conn.select(ROOMS_SPACE)
        if not result.data:
            return 1
        max_id = max(row[0] for row in result.data)
        return max_id + 1

    @staticmethod
    def _row_to_dict(row: list) -> dict[str, Any]:
        """Convert a Tarantool row to a dictionary."""
        return {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "yjs_state": row[3],  # bytes or None
            "content": row[4] or "",
            "updated_at": row[5],
        }


# Module-level singleton
tarantool_client = TarantoolClient()
