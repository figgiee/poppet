"""Wire framing for the legacy socket protocol (kept for poc_client + future use).

The runtime architecture pivoted to file-sync (see cascadeur_connection.py), but
the framed-message format is still used by scripts/poc_client.py and is a small,
self-contained reference for any future socket reintroduction.

Frame layout:
    [ 64-byte ASCII header — decimal length, right-padded with spaces ][ UTF-8 JSON body ]
"""

from __future__ import annotations

import json
from typing import Any

HEADER_LEN = 64


def encode(message: dict[str, Any]) -> bytes:
    """Encode a JSON message into a framed wire blob.

    The header is the decimal length of the body in ASCII, padded on the right
    with spaces to exactly HEADER_LEN bytes.
    """
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = str(len(body)).encode("ascii")
    if len(header) > HEADER_LEN:
        raise ValueError(
            f"message too large to frame: {len(body)} bytes (max header is {HEADER_LEN})"
        )
    header += b" " * (HEADER_LEN - len(header))
    return header + body


def parse_header(header_bytes: bytes) -> int:
    """Parse a 64-byte ASCII header into the body length."""
    if len(header_bytes) != HEADER_LEN:
        raise ValueError(f"header must be exactly {HEADER_LEN} bytes, got {len(header_bytes)}")
    text = header_bytes.decode("ascii").strip()
    if not text:
        raise ValueError("empty header")
    try:
        return int(text)
    except ValueError as e:
        raise ValueError(f"header is not a decimal length: {text!r}") from e
