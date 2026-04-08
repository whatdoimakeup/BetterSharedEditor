"""
Views for the core app.
"""

import json
import logging
from datetime import datetime, timezone
import time

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services.tarantool import tarantool_client
from .services.centrifugo import CentrifugoClient
from .services.redis_state import room_state_cache
from .services.s3 import s3_service

centrifugo_client = CentrifugoClient()

logger = logging.getLogger(__name__)


def _load_state_from_storage(room_id: int) -> tuple[bytes | None, str]:
    """Load current room state from Redis first, then fall back to S3."""
    a = time.perf_counter()
    cached_state, cached_content = room_state_cache.get_room_state(room_id)
    b = time.perf_counter()
    logger.info(f"Loaded state for room {room_id} from Redis in {(b - a) * 1000:.2f} ms")
    if cached_state is not None or cached_content is not None:
        return cached_state, cached_content or ""

    from .services.yjs import get_text_from_state

    state_bytes = s3_service.download_room_state(room_id)
    if not state_bytes:
        return None, ""

    content = get_text_from_state(state_bytes)
    room_state_cache.warm_room_state(room_id, state_bytes, content)
    return state_bytes, content


def _serialize_room(room: dict) -> dict:
    """Build API room metadata without relying on Tarantool-stored state."""
    current_state, current_content = _load_state_from_storage(room["id"])
    return {
        "id": room["id"],
        "name": room["name"],
        "created_at": room["created_at"],
        "updated_at": room["updated_at"],
        "has_content": bool(current_content),
        "has_state": current_state is not None,
    }


# ============================================================
# Room CRUD Views
# ============================================================


class RoomListCreateView(APIView):
    """List all rooms or create a new one."""

    def get(self, request):
        """Return list of all rooms."""
        try:
            rooms = tarantool_client.list_rooms()
            rooms_safe = [_serialize_room(room) for room in rooms]
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
            return Response(_serialize_room(room), status=status.HTTP_201_CREATED)
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
            return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(_serialize_room(room))

    def delete(self, request, room_id):
        """Delete a room."""
        success = tarantool_client.delete_room(room_id)
        if not success:
            return Response(
                {"error": "Failed to delete room"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        room_state_cache.clear_room_state(room_id)
        s3_service.delete_room_state(room_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoomStateView(APIView):
    """Get or update the persisted Yjs state of a room."""

    def get(self, request, room_id):
        """Return room content and Yjs state (base64 encoded)."""
        room = tarantool_client.get_room(room_id)
        if not room:
            return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

        from .services.yjs import encode_yjs_state

        current_yjs_state, current_content = _load_state_from_storage(room_id)

        response_data = {
            "id": room["id"],
            "name": room["name"],
            "content": current_content,
        }

        if current_yjs_state:
            response_data["yjs_state"] = encode_yjs_state(current_yjs_state)
        else:
            response_data["yjs_state"] = None

        return Response(response_data)


# ============================================================
# Centrifugo RPC proxy
# ============================================================


def _get_room_snapshot(room_id: int):
    """Get room metadata from Tarantool and current state from Redis/S3."""
    room = tarantool_client.get_room(room_id)
    if not room:
        return None, None, None

    state_bytes, content = _load_state_from_storage(room_id)
    return room, state_bytes, content


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

    if method not in ["yjs_update", "yjs_http_update"]:
        return JsonResponse({"error": f"Unknown RPC method: {method}"}, status=400)

    room_id = params.get("room_id")
    update_b64 = params.get("data")
    sender_id = params.get("sender_id", "")

    if method == "yjs_http_update":
        # Broadcast resync event to all OTHER clients on the channel.
        centrifugo_client.publish_to_room(
            room_id,
            {
                "type": "room-resync-needed",
                "senderId": sender_id,
            },
        )
        return JsonResponse({"result": {}})

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

    cache_update_count = room_state_cache.save_room_state(room_id, new_state_bytes, text_content)

    # Broadcast the original delta to all channel subscribers immediately
    centrifugo_client.publish_to_room(
        room_id,
        {
            "type": "yjs-update",
            "senderId": sender_id,
            "data": update_b64,
        },
    )

    # Persist to S3 every 10th request, or every request if Redis is unavailable.
    if cache_update_count is None or cache_update_count % 10 == 0:
        try:
            s3_service.upload_room_state(room_id, new_state_bytes)
        except Exception as e:
            logger.error("Failed to flush room %s state to S3: %s", room_id, e)
            return JsonResponse({"error": "Failed to save state"}, status=500)

        updated_room = tarantool_client.touch_room(room_id)
        if not updated_room:
            return JsonResponse({"error": "Failed to update room metadata"}, status=500)

        logger.info(
            "Flushed room %s from Redis cache to S3 on update #%s",
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
        yjs_state_b64 = request.data.get("update")
        sender_id = request.data.get("sender_id", "")

        if not yjs_state_b64:
            return Response(
                {"error": "Missing update"},
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
            return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

        logger.info(f"[upload-update] Existing state: {len(existing_state) if existing_state else 0} bytes")

        # Apply update to CRDT state via pycrdt
        try:
            new_state_bytes, text_content = apply_yjs_update(existing_state, update_bytes)
            logger.info(
                f"[upload-update] Applied update, new state: {len(new_state_bytes)} bytes, text: {len(text_content)} chars"
            )
        except Exception as e:
            logger.error("Failed to merge Yjs update for room %s: %s", room_id, e)
            return Response(
                {"error": "Failed to merge update"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        cache_update_count = room_state_cache.save_room_state(room_id, new_state_bytes, text_content)

        logger.info("[upload-update] Saved latest state to Redis, publishing room-resync-needed")

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
            try:
                s3_service.upload_room_state(room_id, new_state_bytes)
            except Exception as e:
                logger.error("[upload-update] Failed to upload room %s state to S3: %s", room_id, e)
                return Response(
                    {"error": "Failed to save state"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            updated_room = tarantool_client.touch_room(room_id)
            if not updated_room:
                logger.error(f"[upload-update] Failed to update room {room_id}")
                return Response(
                    {"error": "Failed to update room metadata"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            updated_at = updated_room["updated_at"]
            logger.info(
                "[upload-update] Flushed room %s from Redis cache to S3 on update #%s",
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
