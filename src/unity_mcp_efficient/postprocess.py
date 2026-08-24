"""Unity-aware defaults and lossy previews; raw data remains in ResultStore."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from .catalog import OperationSpec

_DEFAULT_ARGUMENTS: dict[str, dict[str, Any]] = {
    "console.get": {
        "types": ["error", "warning"],
        "count": 20,
        "format": "plain",
        "include_stacktrace": False,
    },
    "scene.get_hierarchy": {"page_size": 50, "include_transform": False},
    "asset.search": {"page_size": 10, "generate_preview": False},
    "camera.screenshot": {"max_resolution": 512, "include_image": False},
    "tests.run": {"include_details": False},
    "tests.result": {"include_details": False},
}


def prepare_arguments(
    spec: OperationSpec,
    arguments: dict[str, Any] | None,
    *,
    unity_instance: str | None = None,
) -> dict[str, Any]:
    prepared = dict(_DEFAULT_ARGUMENTS.get(spec.name, {}))
    prepared.update(arguments or {})
    if spec.action is not None:
        prepared["action"] = spec.action
    if unity_instance:
        prepared["unity_instance"] = unity_instance
    missing = [key for key in spec.required_args if key not in prepared]
    if missing:
        raise ValueError(
            f"Missing required arguments for {spec.name}: {', '.join(missing)}"
        )
    return prepared


def prepare_preview(operation: str, value: Any) -> Any:
    """Keep intent and diagnostics while dropping repetitive Unity serialization."""
    unwrapped = _unwrap(value)
    if operation == "scene.get_hierarchy":
        return _hierarchy(unwrapped)
    if operation == "console.get":
        return _console(unwrapped)
    if operation == "tests.run":
        return _async_job(unwrapped)
    if operation.startswith("tests."):
        return _tests(unwrapped)
    if operation.startswith("build."):
        return _build(unwrapped)
    if operation.startswith("probuilder."):
        return _geometry(unwrapped)
    return _strip_noise(unwrapped)


def _async_job(value: Any) -> Any:
    """Return the polling contract immediately instead of a bulky async envelope."""
    if not isinstance(value, dict):
        return _strip_noise(value)
    selected: dict[str, Any] = {}
    nested = value.get("data")
    if isinstance(nested, dict):
        for key in (
            "job_id",
            "jobId",
            "status",
            "state",
            "mode",
            "message",
            "success",
        ):
            if key in nested and nested[key] not in (None, ""):
                selected["job_id" if key == "jobId" else key] = nested[key]
    for key in ("job_id", "jobId", "status", "state", "mode", "message", "success"):
        if key in value and value[key] not in (None, ""):
            selected["job_id" if key == "jobId" else key] = value[key]
    return _strip_noise(selected or value)


def _unwrap(value: Any) -> Any:
    if not isinstance(value, dict) or "data" not in value:
        return value
    envelope = {
        key: value[key]
        for key in ("success", "status", "message", "error")
        if key in value and value[key] not in (None, "", True)
    }
    if not envelope:
        return value["data"]
    envelope["data"] = value["data"]
    return envelope


def _strip_noise(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<depth omitted>"
    if isinstance(value, list):
        return [_strip_noise(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).casefold()
        if item is None or item == "":
            continue
        if lowered in {"stacktrace", "stack_trace", "raw", "serializedobject"}:
            continue
        if lowered == "tag" and item == "Untagged":
            continue
        if lowered == "layer" and item in {0, "Default"}:
            continue
        if (
            lowered in {"active", "activeinhierarchy", "active_self", "enabled"}
            and item is True
        ):
            continue
        result[str(key)] = _strip_noise(item, depth + 1)
    return result


def _hierarchy(value: Any) -> Any:
    def node(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        children = item.get("children") or []
        components = item.get("components") or item.get("componentTypes") or []
        compact: dict[str, Any] = {}
        for source, target in (
            ("name", "name"),
            ("instanceID", "id"),
            ("instanceId", "id"),
            ("path", "path"),
            ("activeSelf", "active"),
        ):
            if source in item and target not in compact:
                compact[target] = item[source]
        if components:
            compact["components"] = [
                entry.get("type") or entry.get("name")
                if isinstance(entry, dict)
                else entry
                for entry in components
            ]
        if children:
            compact["children"] = [node(child) for child in children]
        for key in ("tag", "layer", "active", "isActive"):
            if key in item:
                compact[key] = item[key]
        return _strip_noise(compact)

    def container(item: Any) -> Any:
        if isinstance(item, list):
            return [node(entry) for entry in item]
        if not isinstance(item, dict):
            return item
        result: dict[str, Any] = {}
        for key, nested in item.items():
            if key in {"roots", "objects", "gameObjects", "items"} and isinstance(
                nested, list
            ):
                result[key] = [node(entry) for entry in nested]
            elif isinstance(nested, dict):
                result[key] = container(nested)
            else:
                result[key] = nested
        return _strip_noise(result)

    return container(value)


def _console(value: Any) -> Any:
    entries = _find_list(value, ("entries", "logs", "items", "messages", "data"))
    if entries is None:
        return _strip_noise(value)
    groups: Counter[tuple[str, str, str, str]] = Counter()
    diagnostics: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for entry in entries:
        if isinstance(entry, dict):
            kind = str(entry.get("type") or entry.get("logType") or "log")
            message = str(entry.get("message") or entry.get("text") or "")
            file_name = str(entry.get("file") or entry.get("filePath") or "")
            line = str(entry.get("line") or entry.get("lineNumber") or "")
            stack = str(entry.get("stackTrace") or entry.get("stack_trace") or "")
        else:
            kind, message, file_name, line, stack = "log", str(entry), "", "", ""
        message = re.sub(r"\s+", " ", message).strip()
        key = (kind, message, file_name, line)
        groups[key] += 1
        if key not in diagnostics:
            project_frame = _first_project_frame(stack)
            root_cause = _root_cause(message, stack)
            diagnostics[key] = {
                **({"project_frame": project_frame} if project_frame else {}),
                **({"root_cause": root_cause} if root_cause else {}),
            }
    compact = []
    for (kind, message, file_name, line), repeats in groups.most_common():
        fingerprint = hashlib.sha1(
            f"{kind}\0{message}\0{file_name}\0{line}".encode()
        ).hexdigest()[:10]
        item: dict[str, Any] = {
            "type": kind,
            "message": message,
            "fingerprint": fingerprint,
            **diagnostics[(kind, message, file_name, line)],
        }
        if repeats > 1:
            item["repeats"] = repeats
        if file_name:
            item["file"] = file_name
        if line:
            item["line"] = line
        compact.append(item)
    return {
        "entry_count": len(entries),
        "unique_count": len(compact),
        "error_count": sum(
            repeats
            for (kind, _, _, _), repeats in groups.items()
            if kind.casefold() in {"error", "exception", "assert"}
        ),
        "warning_count": sum(
            repeats
            for (kind, _, _, _), repeats in groups.items()
            if kind.casefold() in {"warning", "warn"}
        ),
        "entries": compact,
    }


def _first_project_frame(stack: str) -> str:
    for line in stack.splitlines():
        normalized = line.strip()
        match = re.search(
            r"(?:Assets|Packages)[/\\][^()\r\n]+?\.cs(?::\d+)?", normalized
        )
        if match:
            return match.group(0)[:300]
    return ""


def _root_cause(message: str, stack: str) -> str:
    candidates = [message]
    candidates.extend(
        line.strip()
        for line in stack.splitlines()
        if re.search(r"\b(?:Exception|Error):", line, re.IGNORECASE)
    )
    return re.sub(r"\s+", " ", candidates[-1]).strip()[:300] if candidates else ""


def _tests(value: Any) -> Any:
    failures: list[Any] = []
    entries = _find_list(value, ("tests", "results", "items", "data"))
    if entries:
        for entry in entries:
            if isinstance(entry, dict):
                status = str(
                    entry.get("status") or entry.get("result") or ""
                ).casefold()
                if status in {"failed", "failure", "error", "inconclusive"}:
                    failures.append(_strip_noise(entry))
    if failures:
        return {"failed_count": len(failures), "failures": failures}
    return _strip_noise(value)


def _build(value: Any) -> Any:
    if not isinstance(value, dict):
        return _strip_noise(value)
    keep = (
        "success",
        "status",
        "result",
        "outputPath",
        "duration",
        "errors",
        "warnings",
        "message",
    )
    selected = {key: value[key] for key in keep if key in value}
    return _strip_noise(selected or value)


def _geometry(value: Any, depth: int = 0) -> Any:
    """Replace verbose topology buffers with counts and spatial invariants."""
    if depth > 8:
        return "<depth omitted>"
    if isinstance(value, list):
        return [_geometry(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).casefold().replace("_", "")
        if isinstance(item, list) and lowered in {
            "vertices",
            "vertexpositions",
            "positions",
        }:
            result[str(key)] = _vector_buffer_summary(item)
        elif isinstance(item, list) and lowered in {
            "faces",
            "triangles",
            "edges",
            "indices",
            "normals",
            "tangents",
            "uvs",
        }:
            result[str(key)] = {
                "count": len(item),
                **({"sample": item[:3]} if item else {}),
            }
        else:
            result[str(key)] = _geometry(item, depth + 1)
    return _strip_noise(result)


def _vector_buffer_summary(values: list[Any]) -> dict[str, Any]:
    vectors: list[list[float]] = []
    for value in values:
        if isinstance(value, dict) and all(axis in value for axis in ("x", "y")):
            coordinates = [value["x"], value["y"]]
            if "z" in value:
                coordinates.append(value["z"])
        elif isinstance(value, (list, tuple)) and 2 <= len(value) <= 4:
            coordinates = list(value)
        else:
            continue
        try:
            vectors.append([float(component) for component in coordinates])
        except (TypeError, ValueError):
            continue
    summary: dict[str, Any] = {"count": len(values)}
    if not vectors:
        if values:
            summary["sample"] = values[:3]
        return summary
    dimensions = min(len(vector) for vector in vectors)
    minimum = [min(vector[index] for vector in vectors) for index in range(dimensions)]
    maximum = [max(vector[index] for vector in vectors) for index in range(dimensions)]
    centroid = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimensions)
    ]
    summary.update(
        bounds={"min": minimum, "max": maximum},
        centroid=[round(value, 6) for value in centroid],
        sample=values[:2],
    )
    return summary


def _find_list(value: Any, keys: tuple[str, ...]) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                nested = _find_list(candidate, keys)
                if nested is not None:
                    return nested
    return None
