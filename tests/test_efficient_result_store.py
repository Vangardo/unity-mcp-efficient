import pytest

from unity_mcp_efficient.result_store import (
    ResultStore,
    resolve_json_pointer,
    select_result,
)


def test_store_roundtrip_pointer_and_paging():
    store = ResultStore(ttl_seconds=60, max_items=2, max_bytes=10_000)
    info = store.put(
        {"data": {"items": list(range(10))}}, operation="demo", mutating=False, ok=True
    )
    value, restored = store.get(info.result_id)
    assert restored.operation == "demo"
    assert resolve_json_pointer(value, "/data/items/3") == 3
    page = select_result(value, path="/data/items", offset=4, limit=3)
    assert page["data"] == [4, 5, 6]
    assert page["has_more"] is True


def test_store_expires_results():
    now = [10.0]
    store = ResultStore(
        ttl_seconds=1, max_items=2, max_bytes=10_000, clock=lambda: now[0]
    )
    info = store.put({"value": 1}, operation="demo", mutating=False, ok=True)
    now[0] = 12.0
    with pytest.raises(KeyError, match="expired"):
        store.get(info.result_id)


def test_durable_store_and_request_receipt_survive_restart(tmp_path):
    database = tmp_path / "results.sqlite3"
    first = ResultStore(
        ttl_seconds=60,
        max_items=10,
        max_bytes=100_000,
        database_path=database,
    )
    info = first.put(
        {"success": True, "id": 42},
        operation="gameobject.create",
        mutating=True,
        ok=True,
    )
    first.remember_request(
        "create-crate-1", fingerprint="same-arguments", result_id=info.result_id
    )

    restarted = ResultStore(
        ttl_seconds=60,
        max_items=10,
        max_bytes=100_000,
        database_path=database,
    )
    value, restored = restarted.get_request(
        "create-crate-1", fingerprint="same-arguments"
    )
    assert value["id"] == 42
    assert restored.result_id == info.result_id

    with pytest.raises(ValueError, match="different arguments"):
        restarted.get_request("create-crate-1", fingerprint="changed")
