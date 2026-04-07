"""
Redis-backed hot cache for collaborative room state.

The Go RPC service (go-rpc) stores raw Yjs binary updates in a per-room
pending list (``room:<id>:pending_updates``) instead of doing the expensive
CRDT merge on every keystroke.  Django reads and merges that list lazily
whenever the full room state is actually needed — on room load or explicit
state request.
"""

import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Lua script: atomically return all items in the list and delete it.
# This prevents losing updates that arrive between LRANGE and DEL.
_GET_AND_CLEAR_LUA = """
local items = redis.call('LRANGE', KEYS[1], 0, -1)
if #items > 0 then
    redis.call('DEL', KEYS[1])
end
return items
"""

# Maximum number of raw updates kept in the pending list per room.
_MAX_PENDING_UPDATES = 10_000
# TTL for the pending list key (30 minutes).
_PENDING_UPDATES_TTL = 1_800


class RoomStateCache:
    """Cache the latest Yjs room state in Redis and periodically flush to DB."""

    _instance = None
    _client: redis.Redis | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_client(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client

        try:
            self._client = redis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            self._client.ping()
            logger.info("Connected to Redis at %s", settings.REDIS_URL)
        except Exception as error:
            logger.warning("Redis unavailable, falling back to DB writes: %s", error)
            self._client = None

        return self._client

    @staticmethod
    def _state_key(room_id: int) -> str:
        return f"room:{room_id}:state"

    @staticmethod
    def _content_key(room_id: int) -> str:
        return f"room:{room_id}:content"

    @staticmethod
    def _counter_key(room_id: int) -> str:
        return f"room:{room_id}:update_count"

    @staticmethod
    def _pending_key(room_id: int) -> str:
        return f"room:{room_id}:pending_updates"

    def get_room_state(self, room_id: int) -> tuple[bytes | None, str | None]:
        client = self._get_client()
        if client is None:
            return None, None

        try:
            state, content = client.mget(
                [self._state_key(room_id), self._content_key(room_id)]
            )
        except redis.RedisError as error:
            logger.error("Redis read failed for room %s: %s", room_id, error)
            self._client = None
            return None, None

        if state is None and content is None:
            return None, None

        content_text = (
            content.decode("utf-8")
            if isinstance(content, (bytes, bytearray))
            else content
        )
        return state, content_text if content_text is not None else ""

    def warm_room_state(
        self, room_id: int, yjs_state: bytes | None, content: str
    ) -> None:
        client = self._get_client()
        if client is None:
            return

        ttl = settings.REDIS_ROOM_STATE_TTL_SECONDS

        try:
            pipeline = client.pipeline()
            pipeline.set(self._state_key(room_id), yjs_state or b"")
            pipeline.set(self._content_key(room_id), content)
            pipeline.expire(self._state_key(room_id), ttl)
            pipeline.expire(self._content_key(room_id), ttl)
            pipeline.execute()
        except redis.RedisError as error:
            logger.error("Redis warm-up failed for room %s: %s", room_id, error)
            self._client = None

    def save_room_state(
        self,
        room_id: int,
        yjs_state: bytes | None,
        content: str,
    ) -> int | None:
        client = self._get_client()
        if client is None:
            return None

        ttl = settings.REDIS_ROOM_STATE_TTL_SECONDS

        try:
            pipeline = client.pipeline()
            pipeline.set(self._state_key(room_id), yjs_state or b"", ex=ttl)
            pipeline.set(self._content_key(room_id), content, ex=ttl)
            pipeline.incr(self._counter_key(room_id))
            pipeline.expire(self._counter_key(room_id), ttl)
            results = pipeline.execute()
            return int(results[2])
        except redis.RedisError as error:
            logger.error("Redis write failed for room %s: %s", room_id, error)
            self._client = None
            return None

    def get_and_clear_pending_updates(self, room_id: int) -> list[bytes]:
        """Atomically fetch and remove all pending raw Yjs updates for a room.

        These updates were written by the Go RPC service on every client edit.
        Django calls this method when it needs the full room state so it can
        merge the updates into the persisted Yjs document via pycrdt.

        Returns an empty list when Redis is unavailable or there are no updates.
        """
        client = self._get_client()
        if client is None:
            return []

        key = self._pending_key(room_id)
        try:
            result = client.eval(_GET_AND_CLEAR_LUA, 1, key)
            return [bytes(item) for item in result] if result else []
        except redis.RedisError as error:
            logger.error(
                "Redis get_and_clear_pending_updates failed for room %s: %s",
                room_id,
                error,
            )
            self._client = None
            return []

    def clear_room_state(self, room_id: int) -> None:
        client = self._get_client()
        if client is None:
            return

        try:
            client.delete(
                self._state_key(room_id),
                self._content_key(room_id),
                self._counter_key(room_id),
                self._pending_key(room_id),
            )
        except redis.RedisError as error:
            logger.error("Redis delete failed for room %s: %s", room_id, error)
            self._client = None


room_state_cache = RoomStateCache()
