"""Small deterministic workflow primitives for token-efficient MCP batches.

The module intentionally supports data selection and comparisons, not arbitrary
code execution.  That keeps workflows auditable while moving repetitive loops,
polling, and large intermediate payloads out of the model context.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_STEP_REF = re.compile(r"^\$steps\.(\d+)(?:\.(.+))?$")
_ITEM_REF = re.compile(r"^\$item(?:\.(.+))?$")
_MISSING = object()


def select_path(value: Any, path: str = "") -> Any:
    """Select a dotted path from mappings/sequences."""
    current = value
    normalized = path.strip().strip(".")
    if not normalized:
        return current
    for part in normalized.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                raise KeyError(f"Path component not found: {part}")
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            current = current[int(part)]
        else:
            raise TypeError(f"Cannot select {part!r} through {type(current).__name__}")
    return current


def resolve_references(
    value: Any,
    steps: list[Any],
    *,
    item: Any = _MISSING,
) -> Any:
    """Resolve exact ``$steps.N.path`` and ``$item.path`` references."""
    if isinstance(value, list):
        return [resolve_references(entry, steps, item=item) for entry in value]
    if isinstance(value, dict):
        return {
            key: resolve_references(entry, steps, item=item)
            for key, entry in value.items()
        }
    if not isinstance(value, str):
        return value

    step_match = _STEP_REF.match(value)
    if step_match:
        index = int(step_match.group(1))
        if index >= len(steps):
            raise ValueError(f"Step reference points to unavailable step {index}")
        return select_path(steps[index], step_match.group(2) or "")

    item_match = _ITEM_REF.match(value)
    if item_match:
        if item is _MISSING:
            raise ValueError("$item is only available inside a foreach step")
        return select_path(item, item_match.group(1) or "")
    return value


def evaluate_condition(
    condition: dict[str, Any],
    steps: list[Any],
    *,
    current: Any = _MISSING,
    item: Any = _MISSING,
) -> bool:
    """Evaluate one bounded declarative condition."""
    if not isinstance(condition, dict):
        raise TypeError("condition must be an object")
    if "left" in condition:
        actual = resolve_references(condition["left"], steps, item=item)
    elif current is not _MISSING:
        actual = current
    else:
        raise ValueError("condition requires left or a current value")
    path = str(condition.get("path") or "")
    if path:
        try:
            actual = select_path(actual, path)
        except (KeyError, IndexError, ValueError, TypeError):
            if str(condition.get("op") or "").casefold() == "exists":
                return False
            raise

    operator = str(condition.get("op") or "truthy").casefold()
    expected = resolve_references(condition.get("value"), steps, item=item)
    if operator in {"eq", "equals", "=="}:
        return actual == expected
    if operator in {"ne", "not_equals", "!="}:
        return actual != expected
    if operator in {"gt", ">"}:
        return actual > expected
    if operator in {"gte", ">="}:
        return actual >= expected
    if operator in {"lt", "<"}:
        return actual < expected
    if operator in {"lte", "<="}:
        return actual <= expected
    if operator == "contains":
        return expected in actual
    if operator == "in":
        return actual in expected
    if operator == "exists":
        return actual is not None
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not actual
    raise ValueError(f"Unsupported condition operator: {operator}")


def select_value(
    source: Any,
    *,
    path: str = "",
    where: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    sort_by: str | None = None,
    descending: bool = False,
    limit: int = 50,
    aggregate: str | None = None,
    steps: list[Any] | None = None,
) -> Any:
    """Filter/project/aggregate one intermediate result without model round trips."""
    selected = select_path(source, path)
    context = steps or []
    if where is not None:
        if not isinstance(selected, list):
            raise ValueError("where requires a list source")
        selected = [
            entry
            for entry in selected
            if evaluate_condition(where, context, current=entry)
        ]
    if sort_by:
        if not isinstance(selected, list):
            raise ValueError("sort_by requires a list source")
        selected = sorted(
            selected,
            key=lambda entry: select_path(entry, sort_by),
            reverse=bool(descending),
        )
    if isinstance(selected, list):
        selected = selected[: max(0, min(int(limit), 500))]
    if fields:
        if isinstance(selected, list):
            selected = [
                {field: select_path(entry, field) for field in fields}
                for entry in selected
            ]
        else:
            selected = {field: select_path(selected, field) for field in fields}

    if aggregate:
        values = selected if isinstance(selected, list) else [selected]
        operation = aggregate.casefold()
        if operation == "count":
            return len(values)
        if operation == "sum":
            return sum(values)
        if operation == "min":
            return min(values)
        if operation == "max":
            return max(values)
        if operation in {"avg", "mean"}:
            return sum(values) / len(values) if values else None
        raise ValueError(f"Unsupported aggregate: {aggregate}")
    return selected


def contains_step_reference(value: Any) -> bool:
    """Return whether a structure contains a step dependency."""
    if isinstance(value, str):
        return bool(_STEP_REF.match(value))
    if isinstance(value, list):
        return any(contains_step_reference(entry) for entry in value)
    if isinstance(value, dict):
        return any(contains_step_reference(entry) for entry in value.values())
    return False
