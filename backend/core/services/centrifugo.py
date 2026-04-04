"""
Centrifugo server API service.

Handles publishing messages, presence info, and token generation
via Centrifugo's HTTP API.
"""

import base64
import hashlib
import hmac
import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class CentrifugoClient:
    """Client for Centrifugo server-side HTTP API."""

    def __init__(self):
        self.api_url = f"{settings.CENTRIFUGO_API_URL}/api".rstrip("/")
        self.api_key = settings.CENTRIFUGO_API_KEY
        self.hmac_key = settings.CENTRIFUGO_HMAC_KEY
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"apikey {self.api_key}",
            }
        )

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an API call to Centrifugo."""
        payload = {"method": method, "params": params or {}}
        try:
            response = self._session.post(self.api_url, json=payload, timeout=5)
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                logger.error("Centrifugo API error: %s", result["error"])
            return result
        except requests.RequestException as e:
            logger.error("Centrifugo API call failed: %s", e)
            return {}

    # --- Publishing ---

    def publish(self, channel: str, data: dict[str, Any]) -> bool:
        """Publish a message to a channel."""
        result = self._call("publish", {"channel": channel, "data": data})
        return "result" in result

    def publish_to_room(self, room_id: int, data: dict[str, Any]) -> bool:
        """Publish a message to a room channel."""
        channel = f"rooms:{room_id}"
        return self.publish(channel, data)

    # --- Presence ---

    def presence(self, channel: str) -> dict[str, Any]:
        """Get presence info for a channel."""
        result = self._call("presence", {"channel": channel})
        return result.get("result", {}).get("presence", {})

    def presence_stats(self, channel: str) -> dict[str, int]:
        """Get presence stats (num_clients, num_users) for a channel."""
        result = self._call("presence_stats", {"channel": channel})
        return result.get("result", {})

    def room_presence(self, room_id: int) -> dict[str, Any]:
        """Get presence info for a room."""
        channel = f"rooms:{room_id}"
        return self.presence(channel)

    def room_presence_stats(self, room_id: int) -> dict[str, int]:
        """Get presence stats for a room."""
        channel = f"rooms:{room_id}"
        return self.presence_stats(channel)

    # --- History ---

    def history(self, channel: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get message history for a channel."""
        result = self._call("history", {"channel": channel, "limit": limit})
        return result.get("result", {}).get("publications", [])

    def room_history(self, room_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Get message history for a room."""
        channel = f"rooms:{room_id}"
        return self.history(channel, limit)

    # --- Token Generation for Client SDK ---

    def generate_connection_token(self, user_id: str) -> str:
        """Generate a JWT for Centrifugo client connection.

        This token is used by centrifuge-js on the frontend to authenticate
        the WebSocket connection.
        """
        import jwt
        from datetime import datetime, timedelta, timezone

        payload = {
            "sub": user_id,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        token = jwt.encode(payload, self.hmac_key, algorithm="HS256")
        return token

    def generate_subscription_token(
        self, user_id: str, channel: str
    ) -> str:
        """Generate a JWT for subscribing to a specific channel."""
        import jwt
        from datetime import datetime, timedelta, timezone

        payload = {
            "sub": user_id,
            "channel": channel,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        token = jwt.encode(payload, self.hmac_key, algorithm="HS256")
        return token

    # --- Channels ---

    def channels(self, pattern: str = "") -> list[str]:
        """Get list of channels (optionally by pattern)."""
        params = {}
        if pattern:
            params["pattern"] = pattern
        result = self._call("channels", params)
        return result.get("result", {}).get("channels", [])

    def disconnect(self, user_id: str) -> bool:
        """Disconnect a user from Centrifugo."""
        result = self._call("disconnect", {"user": user_id})
        return "result" in result


# Module-level singleton
centrifugo_client = CentrifugoClient()
