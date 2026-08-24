"""Bounded result storage used by the efficient facade.

Large backend responses stay in-process. The model receives a compact preview and
an opaque handle that can be queried without repeating the Unity operation.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .serialization import to_jsonable


@dataclass(frozen=True)
class StoredResultInfo:
    result_id: str
    operation: str
    mutating: bool
    ok: bool
    created_at: float
    expires_at: float
    original_chars: int
    stored_bytes: int


@dataclass
class _StoredResult:
    info: StoredResultInfo
    compressed_json: bytes


class ResultStore:
    """Thread-safe TTL/LRU store, optionally durable across facade restarts."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 30 * 60,
        max_items: int = 256,
        max_bytes: int = 64 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
        database_path: str | Path | None = None,
    ) -> None:
        if ttl_seconds <= 0 or max_items <= 0 or max_bytes <= 0:
            raise ValueError("ResultStore limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._clock = clock
        self._items: OrderedDict[str, _StoredResult] = OrderedDict()
        self._receipts: dict[str, tuple[str, str, float]] = {}
        self._stored_bytes = 0
        self._lock = threading.RLock()
        self._database: sqlite3.Connection | None = None
        if database_path is not None:
            path = Path(database_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._database = sqlite3.connect(path, check_same_thread=False)
            self._database.execute("PRAGMA journal_mode=WAL")
            self._database.execute("PRAGMA synchronous=NORMAL")
            self._database.executescript(
                """
                CREATE TABLE IF NOT EXISTS results (
                    result_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    mutating INTEGER NOT NULL,
                    ok INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    original_chars INTEGER NOT NULL,
                    stored_bytes INTEGER NOT NULL,
                    compressed_json BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS results_expiry
                    ON results(expires_at);
                CREATE INDEX IF NOT EXISTS results_lru
                    ON results(accessed_at);
                CREATE TABLE IF NOT EXISTS request_receipts (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS request_receipts_expiry
                    ON request_receipts(expires_at);
                """
            )
            self._database.commit()

    def put(
        self,
        value: Any,
        *,
        operation: str,
        mutating: bool,
        ok: bool,
    ) -> StoredResultInfo:
        normalized = to_jsonable(value)
        serialized = json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        compressed = zlib.compress(serialized.encode("utf-8"), level=6)
        now = self._clock()
        result_id = f"res_{secrets.token_urlsafe(9)}"
        info = StoredResultInfo(
            result_id=result_id,
            operation=operation,
            mutating=mutating,
            ok=ok,
            created_at=now,
            expires_at=now + self.ttl_seconds,
            original_chars=len(serialized),
            stored_bytes=len(compressed),
        )
        with self._lock:
            if self._database is not None:
                self._purge_expired_database_locked(now)
                self._database.execute(
                    """
                    INSERT INTO results(
                        result_id, operation, mutating, ok, created_at, accessed_at,
                        expires_at, original_chars, stored_bytes, compressed_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        info.result_id,
                        info.operation,
                        int(info.mutating),
                        int(info.ok),
                        info.created_at,
                        now,
                        info.expires_at,
                        info.original_chars,
                        info.stored_bytes,
                        compressed,
                    ),
                )
                self._evict_database_locked()
                self._database.commit()
                return info
            self._purge_expired_locked(now)
            self._items[result_id] = _StoredResult(info, compressed)
            self._stored_bytes += len(compressed)
            self._evict_locked()
        return info

    def get(self, result_id: str) -> tuple[Any, StoredResultInfo]:
        with self._lock:
            now = self._clock()
            if self._database is not None:
                self._purge_expired_database_locked(now)
                row = self._database.execute(
                    """
                    SELECT operation, mutating, ok, created_at, expires_at,
                           original_chars, stored_bytes, compressed_json
                    FROM results WHERE result_id = ?
                    """,
                    (result_id,),
                ).fetchone()
                if row is None:
                    self._database.commit()
                    raise KeyError(f"Unknown or expired result_id: {result_id}")
                self._database.execute(
                    "UPDATE results SET accessed_at = ? WHERE result_id = ?",
                    (now, result_id),
                )
                self._database.commit()
                info = StoredResultInfo(
                    result_id=result_id,
                    operation=str(row[0]),
                    mutating=bool(row[1]),
                    ok=bool(row[2]),
                    created_at=float(row[3]),
                    expires_at=float(row[4]),
                    original_chars=int(row[5]),
                    stored_bytes=int(row[6]),
                )
                payload = zlib.decompress(row[7]).decode("utf-8")
                return json.loads(payload), info
            self._purge_expired_locked(now)
            item = self._items.get(result_id)
            if item is None:
                raise KeyError(f"Unknown or expired result_id: {result_id}")
            self._items.move_to_end(result_id)
            payload = zlib.decompress(item.compressed_json).decode("utf-8")
            return json.loads(payload), item.info

    def remember_request(
        self,
        request_id: str,
        *,
        fingerprint: str,
        result_id: str,
    ) -> None:
        """Bind an explicit idempotency key to one stored result."""
        normalized = request_id.strip()
        if not normalized or len(normalized) > 120:
            raise ValueError("request_id must contain between 1 and 120 characters")
        now = self._clock()
        with self._lock:
            existing = self._receipt_locked(normalized, now)
            if existing and existing[0] != fingerprint:
                raise ValueError("request_id was already used with different arguments")
            if self._database is not None:
                self._database.execute(
                    """
                    INSERT OR REPLACE INTO request_receipts(
                        request_id, fingerprint, result_id, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (normalized, fingerprint, result_id, now, now + self.ttl_seconds),
                )
                self._database.commit()
                return
            # In-memory receipts are kept separately from large payload accounting.
            self._receipts[normalized] = (
                fingerprint,
                result_id,
                now + self.ttl_seconds,
            )

    def get_request(
        self, request_id: str, *, fingerprint: str
    ) -> tuple[Any, StoredResultInfo] | None:
        """Return a prior result or reject reuse with different arguments."""
        normalized = request_id.strip()
        with self._lock:
            receipt = self._receipt_locked(normalized, self._clock())
        if receipt is None:
            return None
        stored_fingerprint, result_id = receipt
        if stored_fingerprint != fingerprint:
            raise ValueError("request_id was already used with different arguments")
        return self.get(result_id)

    def _receipt_locked(self, request_id: str, now: float) -> tuple[str, str] | None:
        if self._database is not None:
            self._purge_expired_database_locked(now)
            row = self._database.execute(
                "SELECT fingerprint, result_id FROM request_receipts WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            return (str(row[0]), str(row[1])) if row else None
        receipt = self._receipts.get(request_id)
        if receipt is None:
            return None
        if receipt[2] <= now:
            self._receipts.pop(request_id, None)
            return None
        return receipt[0], receipt[1]

    def _purge_expired_locked(self, now: float) -> None:
        expired = [
            key for key, item in self._items.items() if item.info.expires_at <= now
        ]
        for key in expired:
            self._stored_bytes -= len(self._items.pop(key).compressed_json)

    def _evict_locked(self) -> None:
        while len(self._items) > self.max_items:
            _, item = self._items.popitem(last=False)
            self._stored_bytes -= len(item.compressed_json)
        # Preserve the newest result even if it exceeds the nominal byte budget.
        while len(self._items) > 1 and self._stored_bytes > self.max_bytes:
            _, item = self._items.popitem(last=False)
            self._stored_bytes -= len(item.compressed_json)

    def _purge_expired_database_locked(self, now: float) -> None:
        assert self._database is not None
        self._database.execute(
            "DELETE FROM request_receipts WHERE expires_at <= ?", (now,)
        )
        self._database.execute("DELETE FROM results WHERE expires_at <= ?", (now,))

    def _evict_database_locked(self) -> None:
        assert self._database is not None
        count, stored_bytes = self._database.execute(
            "SELECT COUNT(*), COALESCE(SUM(stored_bytes), 0) FROM results"
        ).fetchone()
        while int(count) > self.max_items or (
            int(count) > 1 and int(stored_bytes) > self.max_bytes
        ):
            row = self._database.execute(
                "SELECT result_id, stored_bytes FROM results ORDER BY accessed_at LIMIT 1"
            ).fetchone()
            if row is None:
                break
            self._database.execute(
                "DELETE FROM request_receipts WHERE result_id = ?", (row[0],)
            )
            self._database.execute("DELETE FROM results WHERE result_id = ?", (row[0],))
            count = int(count) - 1
            stored_bytes = int(stored_bytes) - int(row[1])


def default_result_database() -> Path | None:
    """Return the local durable store path, or None when explicitly disabled."""
    configured = os.getenv("UNITY_MCP_RESULT_DB")
    if configured and configured.casefold() in {"off", "none", "memory"}:
        return None
    if configured:
        return Path(configured)
    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "unity-mcp-efficient" / "results-v1.sqlite3"


def resolve_json_pointer(value: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer without evaluating caller code."""
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("path must be an RFC 6901 JSON Pointer such as /data/items/0")

    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Path component not found: {part}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise KeyError(
                    f"List path component must be an integer: {part}"
                ) from exc
            if index < 0 or index >= len(current):
                raise IndexError(f"List index out of range: {index}")
            current = current[index]
        else:
            raise KeyError(f"Cannot descend through {type(current).__name__} at {part}")
    return current


def select_result(
    value: Any,
    *,
    path: str = "",
    offset: int = 0,
    limit: int = 50,
    pattern: str | None = None,
) -> dict[str, Any]:
    """Return a bounded page or text match from a stored result."""
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")

    selected = resolve_json_pointer(value, path)
    if pattern:
        needle = pattern.casefold()
        lines = json.dumps(
            selected, ensure_ascii=False, indent=2, default=str
        ).splitlines()
        matches = [line for line in lines if needle in line.casefold()]
        page = matches[offset : offset + limit]
        return {
            "selection": "grep",
            "path": path,
            "pattern": pattern,
            "offset": offset,
            "limit": limit,
            "total": len(matches),
            "has_more": offset + len(page) < len(matches),
            "data": page,
        }

    if isinstance(selected, (list, tuple)):
        sequence = list(selected)
        page = sequence[offset : offset + limit]
        kind = "list"
        total = len(sequence)
        data: Any = page
    elif isinstance(selected, dict):
        items = list(selected.items())
        page = items[offset : offset + limit]
        kind = "object"
        total = len(items)
        data = dict(page)
    elif isinstance(selected, str):
        lines = selected.splitlines() or [selected]
        page = lines[offset : offset + limit]
        kind = "lines"
        total = len(lines)
        data = page
    else:
        return {
            "selection": "value",
            "path": path,
            "offset": 0,
            "limit": 1,
            "total": 1,
            "has_more": False,
            "data": selected,
        }
    return {
        "selection": kind,
        "path": path,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": offset + len(page) < total,
        "data": data,
    }
