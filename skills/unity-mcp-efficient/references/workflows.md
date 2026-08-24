# Bounded workflow grammar

Use workflow steps only when they replace model round trips or prevent bulky intermediate data from entering context. The existing `{operation, arguments}` shape remains a `call` step.

References are exact whole values:

- `$steps.0.data.id` selects a prior raw result.
- `$item.name` is available inside `foreach`.
- Embedded string interpolation is intentionally unsupported.

## Local steps

`select` filters or projects a prior value without returning it to the model:

```json
{"kind":"select","from":"$steps.0.data.items","where":{"path":"active","op":"eq","value":true},"fields":["id","name"],"limit":20}
```

Optional keys are `path`, `where`, `fields`, `sort_by`, `descending`, `limit`, and `aggregate`. Aggregates are `count`, `sum`, `min`, `max`, `avg`, or `mean`.

`assert` stops a sequential workflow when an invariant fails:

```json
{"kind":"assert","condition":{"left":"$steps.1","op":"gt","value":0},"message":"No targets found"}
```

Operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `in`, `exists`, `truthy`, and `falsy`.

`emit` marks the only value the model needs:

```json
{"kind":"emit","value":"$steps.2.data.summary"}
```

Use `response_mode="emits"` to suppress successful step receipts.

## Polling

`poll` repeats one read-only operation server-side and retains only its final raw state:

```json
{
  "kind": "poll",
  "operation": "tests.result",
  "arguments": {"job_id": "$steps.0.data.job_id"},
  "until": {"path": "data.status", "op": "in", "value": ["completed", "failed"]},
  "interval_ms": 500,
  "timeout_ms": 30000
}
```

Intervals are clamped to 100-10000 ms and timeouts to 100-55000 ms. Polling a mutating operation is rejected.

## Foreach

`foreach` expands up to 50 items without asking the model to issue one call per item:

```json
{
  "kind": "foreach",
  "items": "$steps.0",
  "operation": "gameobject.modify",
  "arguments": {"target": "$item.id", "set_active": false},
  "execution": "sequential"
}
```

Mutations are always sequential. `execution="parallel"` is accepted only for operations classified read-only and batch-safe.

## Conditional steps

Any sequential step may have `when` with the same condition shape:

```json
{"operation":"gameobject.create","arguments":{"name":"Fallback"},"when":{"left":"$steps.0","op":"eq","value":0}}
```

A false condition records a successful skipped receipt. Use assertions when a false condition should fail the workflow.

## Mutation recovery

Give each mutating workflow one stable top-level `request_id`. If the response is interrupted, resend the exact request with the same identifier. Never reuse that identifier for modified steps or arguments.
