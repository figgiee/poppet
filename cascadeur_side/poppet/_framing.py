"""Length-prefixed JSON framing for the Poppet wire protocol.

Wire format:
  - 64-byte ASCII length header (right-padded with spaces)
  - UTF-8 JSON body of exactly that many bytes

This module must work in Cascadeur's embedded Python 3.8.
"""

import json

HEADER_LEN = 64


def encode(message):
    """Serialize a dict to length-prefixed bytes."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = str(len(body)).encode("ascii")
    header += b" " * (HEADER_LEN - len(header))
    return header + body


def parse_header(header_bytes):
    """Parse a 64-byte header, return body length."""
    return int(header_bytes.decode("ascii").strip())
