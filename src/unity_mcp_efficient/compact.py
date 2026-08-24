"""Structure-preserving, diagnostic-first output compaction."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

_DIAGNOSTIC_RE = re.compile(
    r"\b(error|exception|traceback|failed|failure|warning|warn|fatal|invalid)\b",
    re.IGNORECASE,
)


@dataclass
class _Stats:
    truncated: bool = False
    omitted_items: int = 0
    omitted_lines: int = 0


def decode_json(value: Any) -> Any:
    """Decode JSON-shaped text while leaving ordinary strings untouched."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return value


def looks_like_error(value: Any) -> bool:
    value = decode_json(value)
    if isinstance(value, dict):
        return bool(value.get("error")) or value.get("status") in {"error", "failed"}
    if isinstance(value, str):
        return bool(
            re.match(r"\s*(error|failed|failure|could not)\b", value, re.IGNORECASE)
        )
    return False


def _compact_text(text: str, *, line_limit: int, char_limit: int, stats: _Stats) -> str:
    if len(text) <= char_limit and text.count("\n") < line_limit:
        return text

    lines = text.splitlines()
    grouped: list[str] = []
    previous: str | None = None
    repeats = 0
    for line in lines:
        normalized = line.rstrip()
        if normalized == previous:
            repeats += 1
            continue
        if repeats:
            grouped.append(f"... previous line repeated {repeats} more times ...")
            repeats = 0
        grouped.append(normalized)
        previous = normalized
    if repeats:
        grouped.append(f"... previous line repeated {repeats} more times ...")

    head = grouped[: max(4, line_limit // 3)]
    tail = grouped[-max(3, line_limit // 5) :]
    diagnostics = [line for line in grouped if _DIAGNOSTIC_RE.search(line)]
    selected: list[str] = []
    seen: set[str] = set()
    for line in [*head, *diagnostics[: line_limit // 2], *tail]:
        if line not in seen:
            selected.append(line)
            seen.add(line)

    omitted = max(0, len(grouped) - len(selected))
    if omitted:
        selected.insert(
            min(len(head), len(selected)), f"... {omitted} lines omitted ..."
        )
        stats.omitted_lines += omitted
        stats.truncated = True
    compacted = "\n".join(selected)
    if len(compacted) > char_limit:
        compacted = (
            compacted[: max(256, char_limit - 32)].rstrip() + "\n... truncated ..."
        )
        stats.truncated = True
    return compacted


def _numeric_summary(values: list[int | float], stats: _Stats) -> dict[str, Any]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    stats.truncated = True
    stats.omitted_items += max(0, len(values) - 4)
    result: dict[str, Any] = {"count": len(values), "sample": values[:4]}
    if finite:
        result.update(
            min=round(min(finite), 6),
            max=round(max(finite), 6),
            mean=round(sum(finite) / len(finite), 6),
        )
    return result


def _compact_value(
    value: Any,
    *,
    item_limit: int,
    line_limit: int,
    char_limit: int,
    depth: int,
    stats: _Stats,
) -> Any:
    if depth > 7:
        stats.truncated = True
        return {"summary": f"{type(value).__name__} omitted beyond depth limit"}
    if isinstance(value, str):
        return _compact_text(
            value, line_limit=line_limit, char_limit=char_limit, stats=stats
        )
    if isinstance(value, dict):
        priority = (
            "error",
            "errors",
            "status",
            "success",
            "message",
            "name",
            "type",
            "count",
            "total",
            "failed",
            "warnings",
            "data",
        )
        keys = [key for key in priority if key in value]
        keys.extend(key for key in value if key not in keys)
        if len(keys) > 48:
            stats.omitted_items += len(keys) - 48
            stats.truncated = True
            keys = keys[:48]
        return {
            str(key): _compact_value(
                value[key],
                item_limit=item_limit,
                line_limit=line_limit,
                char_limit=max(512, char_limit // 2),
                depth=depth + 1,
                stats=stats,
            )
            for key in keys
        }
    if isinstance(value, (list, tuple)):
        sequence = list(value)
        if len(sequence) <= item_limit:
            return [
                _compact_value(
                    item,
                    item_limit=item_limit,
                    line_limit=line_limit,
                    char_limit=max(512, char_limit // 2),
                    depth=depth + 1,
                    stats=stats,
                )
                for item in sequence
            ]
        if all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in sequence
        ):
            return _numeric_summary(sequence, stats)
        sampled = sequence[: max(1, item_limit - 2)] + sequence[-2:]
        omitted = len(sequence) - len(sampled)
        stats.omitted_items += omitted
        stats.truncated = True
        return {
            "count": len(sequence),
            "items": [
                _compact_value(
                    item,
                    item_limit=item_limit,
                    line_limit=line_limit,
                    char_limit=max(512, char_limit // 2),
                    depth=depth + 1,
                    stats=stats,
                )
                for item in sampled
            ],
            "omitted": omitted,
        }
    return value


def _tiny_preview(value: Any, depth: int = 0) -> Any:
    if depth >= 2:
        if isinstance(value, dict):
            return {"type": "object", "key_count": len(value)}
        if isinstance(value, (list, tuple)):
            return {"type": "array", "count": len(value)}
        return str(value)[:120]
    if isinstance(value, dict):
        priority = ("error", "status", "success", "message", "name", "type", "count")
        keys = [key for key in priority if key in value]
        keys.extend(key for key in value if key not in keys)
        return {
            "type": "object",
            "key_count": len(value),
            "keys": [str(key) for key in keys[:16]],
            "preview": {
                str(key): _tiny_preview(value[key], depth + 1) for key in keys[:6]
            },
        }
    if isinstance(value, (list, tuple)):
        return {
            "type": "array",
            "count": len(value),
            "sample": [_tiny_preview(item, depth + 1) for item in list(value)[:3]],
        }
    if isinstance(value, str):
        return {"type": "text", "chars": len(value), "preview": value[:360]}
    return value


def compact_result(
    value: Any,
    mode: str = "compact",
    max_chars: int = 8_000,
    *,
    result_id: str | None = None,
    mutating: bool = False,
) -> dict[str, Any]:
    """Return bounded JSON-shaped data and explicit recovery metadata."""
    if mode not in {"compact", "standard", "full"}:
        raise ValueError("output_mode must be compact, standard, or full")
    budget = max(256, min(int(max_chars), 100_000))
    decoded = decode_json(value)
    original_chars = len(json.dumps(decoded, ensure_ascii=False, default=str))
    if mode == "full" and original_chars <= budget:
        data = decoded
        stats = _Stats()
    else:
        stats = _Stats(truncated=mode == "full")
        item_limit, line_limit = (8, 36) if mode == "compact" else (30, 100)
        data = _compact_value(
            decoded,
            item_limit=item_limit,
            line_limit=line_limit,
            char_limit=budget,
            depth=0,
            stats=stats,
        )
        if len(json.dumps(data, ensure_ascii=False, default=str)) > budget:
            data = _tiny_preview(data)
            stats.truncated = True

    returned_chars = len(json.dumps(data, ensure_ascii=False, default=str))
    meta: dict[str, Any] = {
        "output_mode": mode,
        "truncated": stats.truncated,
        "original_chars": original_chars,
        "returned_chars": returned_chars,
    }
    if stats.omitted_items:
        meta["omitted_items"] = stats.omitted_items
    if stats.omitted_lines:
        meta["omitted_lines"] = stats.omitted_lines
    if result_id:
        meta["result_id"] = result_id
    if mutating:
        meta["mutating"] = True
    if stats.truncated:
        meta["recovery"] = {
            "result_id": result_id,
            "action": "Use get_result with a path, page, or pattern; do not repeat the operation.",
        }
    return {"data": data, "meta": meta}
