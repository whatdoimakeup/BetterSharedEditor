"""
Yjs state encoding/decoding helpers.

Utilities for serializing Yjs document state to/from binary format
for persistence in Tarantool.
"""

import base64
import logging

logger = logging.getLogger(__name__)


def encode_yjs_state(state: bytes) -> str:
    """Encode binary Yjs state to base64 string for API transport."""
    return base64.b64encode(state).decode("utf-8")


def decode_yjs_state(state_b64: str) -> bytes:
    """Decode base64 string back to binary Yjs state."""
    return base64.b64decode(state_b64)


def apply_yjs_update(existing_state: bytes | None, update: bytes) -> tuple[bytes, str]:
    """Apply a Yjs binary update on top of the existing state using pycrdt.

    Returns:
        (new_state_bytes, text_content) — full merged state and plaintext of 'content' key.
    """
    from pycrdt import Doc, Text  # local import to keep startup fast

    doc = Doc()
    if existing_state:
        doc.apply_update(existing_state)
    doc.apply_update(update)

    new_state = doc.get_update()
    text = doc.get("content", type=Text)
    return new_state, str(text)
