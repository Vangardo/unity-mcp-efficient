"""Convert typed MCP/Pydantic values into stable JSON-compatible data."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any


def to_jsonable(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Recursively normalize MCP results before storage or model rendering."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return to_jsonable(value.value, _seen=_seen)
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "bytes": len(value),
            "data": base64.b64encode(value).decode("ascii"),
        }

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return "<recursive reference>"

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        seen.add(identity)
        try:
            try:
                dumped = model_dump(mode="json")
            except TypeError:
                dumped = model_dump()
            return to_jsonable(dumped, _seen=seen)
        finally:
            seen.discard(identity)

    if is_dataclass(value) and not isinstance(value, type):
        seen.add(identity)
        try:
            return to_jsonable(asdict(value), _seen=seen)
        finally:
            seen.discard(identity)

    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            return {
                str(key): to_jsonable(item, _seen=seen)
                for key, item in value.items()
            }
        finally:
            seen.discard(identity)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seen.add(identity)
        try:
            return [to_jsonable(item, _seen=seen) for item in value]
        finally:
            seen.discard(identity)

    if isinstance(value, (set, frozenset)):
        seen.add(identity)
        try:
            return [to_jsonable(item, _seen=seen) for item in value]
        finally:
            seen.discard(identity)

    return str(value)
