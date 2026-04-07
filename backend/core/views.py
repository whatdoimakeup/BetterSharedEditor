"""
Views for the core app.
"""

import json
import logging
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services.tarantool import tarantool_client
from .services.centrifugo import CentrifugoClient
from .services.redis_state import room_state_cache

centrifugo_client = CentrifugoClient()

logger = logging.getLogger(__name__)


# ============================================================
# Room CRUD Views
# ============================================================


class RoomListCreateView(APIView):
    """List all rooms or create a new one."""

    def get(self, request):
        """Return list of all rooms."""
        try:
            rooms = tarantool_client.list_rooms()
            # Strip binary state from list response
            rooms_safe = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "has_content": bool(r.get("content")),
                    "has_state": r.get("yjs_state") is not None,
                }
                for r in rooms
            ]
            return Response({"rooms": rooms_safe})
        except Exception as e:
            logger.error("Failed to list rooms: %s", e)
            return Response(
                {"error": "Failed to fetch rooms"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        """Create a new room."""
        name = request.data.get("name", "").strip()
        if not name:
            return Response(
                {"error": "Room name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            room_id = tarantool_client.get_next_id()
            room = tarantool_client.insert_room(room_id, name)
            room_safe = {
                "id": room["id"],
                "name": room["name"],
                "created_at": room["created_at"],
                "updated_at": room["updated_at"],
                "has_content": False,
                "has_state": False,
            }
            return Response(room_safe, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error("Failed to create room: %s", e)
            return Response(
                {"error": "Failed to create room"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RoomDetailView(APIView):
    """Get details of a specific room."""

    def get(self, request, room_id):
        """Return room details."""
        room = tarantool_client.get_room(room_id)
        if not room:
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )

        room_safe = {
            "id": room["id"],
            "name": room["name"],
            "created_at": room["created_at"],
            "updated_at": room["updated_at"],
            "has_content": bool(room.get("content")),
            "has_state": room.get("yjs_state") is not None,
        }
        return Response(room_safe)

    def delete(self, request, room_id):
        """Delete a room."""
        success = tarantool_client.delete_room(room_id)
        if not success:
            return Response(
                {"error": "Failed to delete room"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        room_state_cache.clear_room_state(room_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoomStateView(APIView):
    """Get or update the persisted Yjs state of a room."""

    def get(self, request, room_id):
        """Return room content and Yjs state (base64 encoded).

        Uses ``_get_room_snapshot`` so any pending raw updates written by the
        Go RPC service are merged in before the state is returned to the client.
        """
        room, current_yjs_state, current_content = _get_room_snapshot(room_id)
        if not room:
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )

        from .services.yjs import encode_yjs_state

        response_data = {
            "id": room["id"],
            "name": room["name"],
            "content": current_content or "",
        }

        if current_yjs_state:
            response_data["yjs_state"] = encode_yjs_state(current_yjs_state)
        else:
            response_data["yjs_state"] = None

        return Response(response_data)

    def post(self, request, room_id):
        """Save Yjs state and content for a room."""
        content = request.data.get("content", "")
        yjs_state_b64 = request.data.get("yjs_state")

        from .services.yjs import decode_yjs_state

        yjs_state_bytes = None
        if yjs_state_b64:
            try:
                yjs_state_bytes = decode_yjs_state(yjs_state_b64)
            except Exception as e:
                logger.error("Failed to decode Yjs state: %s", e)
                return Response(
                    {"error": "Invalid Yjs state encoding"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        room = tarantool_client.update_room_content(
            room_id, content=content, yjs_state=yjs_state_bytes
        )
        if not room:
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )

        room_state_cache.warm_room_state(room_id, yjs_state_bytes, content)
        return Response({"status": "saved", "updated_at": room["updated_at"]})


# ============================================================
# Centrifugo RPC proxy
# ============================================================


def _get_room_snapshot(room_id: int):
    """Get current room state from Redis first, then fall back to Tarantool.

    When the Go RPC service is handling updates it stores raw Yjs bytes in a
    Redis pending list instead of merging them immediately.  This function
    drains that list and applies all pending updates via pycrdt so the
    returned state is always up-to-date, while keeping the hot path (every
    keystroke) in Go and limiting expensive Python CRDT merges to moments
    when the full state is actually needed.
    """
    room = tarantool_client.get_room(room_id)
    if not room:
        return None, None, None

    cached_state, cached_content = room_state_cache.get_room_state(room_id)
    if cached_state is None and cached_content is None:
        existing_state = room.get("yjs_state")
        existing_content = room.get("content") or ""
        room_state_cache.warm_room_state(room_id, existing_state, existing_content)
        base_state = existing_state
        base_content = existing_content
    else:
        base_state = cached_state
        base_content = cached_content or ""

    # Drain any raw updates written by the Go RPC service and merge them.
    pending = room_state_cache.get_and_clear_pending_updates(room_id)
    if pending:
        from .services.yjs import apply_yjs_update

        try:
            state = base_state
            content = base_content
            for update in pending:
                state, content = apply_yjs_update(state, update)

            # Cache the freshly merged state and flush it to Tarantool so it
            # survives a Redis eviction.
            room_state_cache.save_room_state(room_id, state, content)
            tarantool_client.update_room_content(
                room_id, content=content, yjs_state=state
            )
            logger.info(
                "Merged %d pending Go-RPC updates for room %s and flushed to DB",
                len(pending),
                room_id,
            )
            return room, state, content
        except Exception as e:
            logger.error(
                "Failed to merge %d pending updates for room %s: %s",
                len(pending),
                room_id,
                e,
            )
            # Fall through and return the last known good state.

    return room, base_state, base_content


@csrf_exempt
def centrifugo_rpc(request):
    """Handle RPC calls proxied from Centrifugo.

    Centrifugo POST body:
        {method, data: {room_id, data (base64 update), sender_id}, client, ...}
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    method = body.get("method", "")
    params = body.get("data", {})

    if method != "yjs_update":
        return JsonResponse({"error": f"Unknown RPC method: {method}"}, status=400)

    room_id = params.get("room_id")
    update_b64 = params.get("data")
    sender_id = params.get("sender_id", "")

    if not room_id or not update_b64:
        return JsonResponse({"error": "Missing room_id or data"}, status=400)

    from .services.yjs import decode_yjs_state, apply_yjs_update

    # Decode incoming update
    try:
        update_bytes = decode_yjs_state(update_b64)
    except Exception as e:
        logger.error("Failed to decode Yjs update: %s", e)
        return JsonResponse({"error": "Invalid update encoding"}, status=400)

    # Load the hot room state from Redis first, then fall back to Tarantool
    room, existing_state, _ = _get_room_snapshot(room_id)
    if not room:
        return JsonResponse({"error": "Room not found"}, status=404)

    # Apply update to CRDT state via pycrdt
    try:
        new_state_bytes, text_content = apply_yjs_update(existing_state, update_bytes)
    except Exception as e:
        logger.error("Failed to merge Yjs update for room %s: %s", room_id, e)
        return JsonResponse({"error": "Failed to merge update"}, status=500)

    cache_update_count = room_state_cache.save_room_state(
        room_id, new_state_bytes, text_content
    )

    # Broadcast the original delta to all channel subscribers immediately
    centrifugo_client.publish_to_room(
        room_id,
        {
            "type": "yjs-update",
            "senderId": sender_id,
            "data": update_b64,
        },
    )

    # Persist to DB every 10th request, or every request if Redis is unavailable.
    if cache_update_count is None or cache_update_count % 10 == 0:
        updated_room = tarantool_client.update_room_content(
            room_id, content=text_content, yjs_state=new_state_bytes
        )
        if not updated_room:
            return JsonResponse({"error": "Failed to save state"}, status=500)

        logger.info(
            "Flushed room %s from Redis cache to DB on update #%s",
            room_id,
            cache_update_count if cache_update_count is not None else "fallback",
        )

    return JsonResponse({"result": {}})


# ============================================================
# Large Yjs Update Upload via HTTP
# ============================================================


class RoomUploadUpdateView(APIView):
    """Upload a large Yjs update via HTTP (bypasses Centrifugo message size limit).

    POST /api/rooms/:id/upload-update/
    Body: {
        "yjs_state_b64": base64-encoded Yjs binary update,
        "sender_id": client ID
    }

    Returns after persisting:
        {status: "ok", message: "Update applied and broadcast"}
    """

    def post(self, request, room_id):
        """Receive a large Yjs update, merge with DB state, broadcast resync event."""
        yjs_state_b64 = request.data.get("yjs_state_b64")
        sender_id = request.data.get("sender_id", "")

        logger.info(
            f"[upload-update] Received upload from sender={sender_id[:8]}... room_id={room_id} size_b64={len(yjs_state_b64) if yjs_state_b64 else 0}"
        )

        if not yjs_state_b64:
            return Response(
                {"error": "Missing yjs_state_b64"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .services.yjs import decode_yjs_state, apply_yjs_update

        # Decode incoming update
        try:
            update_bytes = decode_yjs_state(yjs_state_b64)
            logger.info(f"[upload-update] Decoded {len(update_bytes)} bytes")
        except Exception as e:
            logger.error("Failed to decode Yjs update: %s", e)
            return Response(
                {"error": "Invalid update encoding"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Load the hot room state from Redis first, then fall back to Tarantool
        room, existing_state, _ = _get_room_snapshot(room_id)
        if not room:
            logger.error(f"[upload-update] Room {room_id} not found")
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )

        logger.info(
            f"[upload-update] Existing state: {len(existing_state) if existing_state else 0} bytes"
        )

        # Apply update to CRDT state via pycrdt
        try:
            new_state_bytes, text_content = apply_yjs_update(
                existing_state, update_bytes
            )
            logger.info(
                f"[upload-update] Applied update, new state: {len(new_state_bytes)} bytes, text: {len(text_content)} chars"
            )
        except Exception as e:
            logger.error("Failed to merge Yjs update for room %s: %s", room_id, e)
            return Response(
                {"error": "Failed to merge update"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        cache_update_count = room_state_cache.save_room_state(
            room_id, new_state_bytes, text_content
        )

        logger.info(
            "[upload-update] Saved latest state to Redis, publishing room-resync-needed"
        )

        # Broadcast resync event to all OTHER clients on the channel.
        centrifugo_client.publish_to_room(
            room_id,
            {
                "type": "room-resync-needed",
                "senderId": sender_id,
            },
        )

        updated_at = datetime.now(timezone.utc).isoformat()

        if cache_update_count is None or cache_update_count % 10 == 0:
            updated_room = tarantool_client.update_room_content(
                room_id, content=text_content, yjs_state=new_state_bytes
            )
            if not updated_room:
                logger.error(f"[upload-update] Failed to update room {room_id}")
                return Response(
                    {"error": "Failed to save state"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            updated_at = updated_room["updated_at"]
            logger.info(
                "[upload-update] Flushed room %s from Redis cache to DB on update #%s",
                room_id,
                cache_update_count if cache_update_count is not None else "fallback",
            )

        logger.info(f"[upload-update] Broadcast complete")

        return Response(
            {
                "status": "ok",
                "message": "Update applied and broadcast",
                "updated_at": updated_at,
            }
        )
