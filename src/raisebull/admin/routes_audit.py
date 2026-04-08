"""Read API for audit_log — GET /admin/api/audit with date + limit filter."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/audit")

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 2000


@router.get("")
async def list_audit(request: Request):
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is None:
        return JSONResponse(
            {"error": "audit log not initialized"}, status_code=503
        )

    qp = request.query_params
    from_ts = qp.get("from")
    to_ts = qp.get("to")

    try:
        limit = int(qp.get("limit", _DEFAULT_LIMIT))
    except ValueError:
        return JSONResponse(
            {"error": "limit must be an integer"}, status_code=400
        )
    if limit < 1 or limit > _MAX_LIMIT:
        return JSONResponse(
            {"error": f"limit must be between 1 and {_MAX_LIMIT}"},
            status_code=400,
        )

    # Fetch limit + 1 to detect truncation without a separate COUNT query
    rows = await audit_log.list_recent(
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit + 1,
    )
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return {
        "rows": rows,
        "truncated": truncated,
        "limit": limit,
        "from": from_ts,
        "to": to_ts,
    }
