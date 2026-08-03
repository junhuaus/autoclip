# REST API contract

Base path: `/api/v1`. The detailed OpenAPI document is generated from FastAPI and must remain consistent with this human contract.

Long-running creation routes return `202 Accepted`, the created resource ID, state, and a polling URL. `POST /jobs`, project import, runs, renders and deliveries accept `Idempotency-Key`; the same key/body returns the same resource while a different body returns 409.

Required resources and routes are enumerated in `docs/PRODUCT_SPEC.md`. Resource DTOs expose IDs, safe names, state/progress/error codes and asset URLs, but not arbitrary absolute local paths, credentials, provider headers, raw exceptions, or ORM internals.

Stable error envelope:

```json
{
  "error": {
    "schema_version": "1",
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe user-facing message",
    "retryable": false,
    "resource_id": null,
    "correlation_id": "...",
    "details": []
  }
}
```

`GET /media/{asset_id}` serves only generated allowlisted Assets below the configured data root. It supports one byte range with 206 and `Content-Range`, returns 416 for invalid/unsatisfiable ranges, advertises `Accept-Ranges: bytes`, and applies the same optional Bearer authentication. SourceMedia is not automatically an Asset.

The server binds to `127.0.0.1` by default. CORS origins are an explicit list. When `LIVECLIP_API_TOKEN` is configured, clients use `Authorization: Bearer …`; the value is never logged or returned.
