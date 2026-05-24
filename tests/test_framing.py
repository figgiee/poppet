"""Unit tests for cascadeur_side.poppet._framing."""

from __future__ import annotations

import json

import pytest
from poppet import _framing


def test_header_len_is_64():
    assert _framing.HEADER_LEN == 64


def test_encode_produces_header_plus_body():
    msg = {"type": "echo", "params": {"hello": "world"}}
    blob = _framing.encode(msg)
    assert len(blob) >= _framing.HEADER_LEN
    header = blob[: _framing.HEADER_LEN]
    body = blob[_framing.HEADER_LEN :]
    # Header is decimal length, right-padded with spaces.
    assert header.endswith(b" ")
    assert int(header.decode("ascii").strip()) == len(body)
    # Body round-trips through JSON.
    assert json.loads(body.decode("utf-8")) == msg


def test_encode_parse_header_round_trip():
    msg = {"type": "scene_info", "params": {}}
    blob = _framing.encode(msg)
    length = _framing.parse_header(blob[: _framing.HEADER_LEN])
    body = blob[_framing.HEADER_LEN : _framing.HEADER_LEN + length]
    assert json.loads(body.decode("utf-8")) == msg


def test_encode_handles_empty_params():
    blob = _framing.encode({"type": "ping", "params": {}})
    length = _framing.parse_header(blob[: _framing.HEADER_LEN])
    assert length == len(blob) - _framing.HEADER_LEN


def test_encode_handles_unicode():
    msg = {"type": "echo", "params": {"greeting": "héllo — 世界"}}
    blob = _framing.encode(msg)
    length = _framing.parse_header(blob[: _framing.HEADER_LEN])
    body = blob[_framing.HEADER_LEN : _framing.HEADER_LEN + length]
    decoded = json.loads(body.decode("utf-8"))
    assert decoded["params"]["greeting"] == "héllo — 世界"


def test_encode_large_payload_round_trip():
    # 100 KB payload — well under any practical header limit, well over one packet.
    big = {"type": "echo", "params": {"blob": "x" * 100_000}}
    blob = _framing.encode(big)
    length = _framing.parse_header(blob[: _framing.HEADER_LEN])
    body = blob[_framing.HEADER_LEN : _framing.HEADER_LEN + length]
    decoded = json.loads(body.decode("utf-8"))
    assert len(decoded["params"]["blob"]) == 100_000


def test_parse_header_wrong_length_rejected():
    with pytest.raises(ValueError, match="header must be exactly"):
        _framing.parse_header(b"123")


def test_parse_header_empty_rejected():
    with pytest.raises(ValueError, match="empty header"):
        _framing.parse_header(b" " * _framing.HEADER_LEN)


def test_parse_header_non_numeric_rejected():
    bad = b"not-a-number".ljust(_framing.HEADER_LEN, b" ")
    with pytest.raises(ValueError, match="not a decimal length"):
        _framing.parse_header(bad)
