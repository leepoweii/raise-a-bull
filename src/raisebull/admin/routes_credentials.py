"""Dashboard credentials CRUD + test API."""

import time

import httpx as httpx_client
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from raisebull.admin.crud import CrudTable

router = APIRouter(prefix="/api/credentials")


def _redact(value: str | None) -> str | None:
    """Return a redacted form of a credential value for audit logging.

    We record only the last 4 characters prefixed with '***' so operators
    can distinguish "this was changed" from "this was ROTATED to the same
    value" without ever storing the full secret. For values shorter than
    4 characters, redact entirely.
    """
    if value is None:
        return None
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def _get_table(request: Request) -> CrudTable:
    return CrudTable(request.app.state.db_path, "credentials")


@router.get("")
async def list_credentials(request: Request):
    return _get_table(request).list(mask_fields=["key_value"])


@router.get("/{cred_id}/reveal")
async def reveal_credential(cred_id: str, request: Request):
    item = _get_table(request).get(cred_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"key_name": item["key_name"], "key_value": item["key_value"], "service": item["service"]}


@router.post("")
async def create_credential(request: Request):
    body = await request.json()
    item = _get_table(request).create({
        "key_name": body["key_name"],
        "key_value": body["key_value"],
        "service": body.get("service", ""),
    })
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        await audit_log.record(
            "credentials.create",
            actor="admin",
            target=body["key_name"],
            before_val=None,
            after_val=_redact(body["key_value"]),
            source_ip=request.client.host if request.client else None,
        )
    return item


@router.put("/{cred_id}")
async def update_credential(cred_id: str, request: Request):
    body = await request.json()
    allowed = {"key_value", "service"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)
    existing = _get_table(request).get(cred_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)

    item = _get_table(request).update(cred_id, data)
    if not item:
        # Race: row was deleted between get() and update(). Treat as 404.
        return JSONResponse({"error": "Not found"}, status_code=404)

    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        after_val = _redact(data["key_value"]) if "key_value" in data else None
        await audit_log.record(
            "credentials.put",
            actor="admin",
            target=existing["key_name"],
            before_val=None,
            after_val=after_val,
            source_ip=request.client.host if request.client else None,
        )
    return {"ok": True}


@router.delete("/{cred_id}")
async def delete_credential(cred_id: str, request: Request):
    existing = _get_table(request).get(cred_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if not _get_table(request).delete(cred_id):
        # Race: row was deleted between get() and delete(). Treat as 404.
        return JSONResponse({"error": "Not found"}, status_code=404)
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        await audit_log.record(
            "credentials.delete",
            actor="admin",
            target=existing["key_name"],
            before_val=None,
            after_val=None,
            source_ip=request.client.host if request.client else None,
        )
    return {"ok": True}


@router.post("/test")
async def test_credential(request: Request):
    """Test a credential by calling the service's health endpoint."""
    body = await request.json()
    key_name = body.get("key_name", "")
    key_value = body.get("key_value", "")

    try:
        start = time.time()
        if key_name == "MINIMAX_API_KEY":
            async with httpx_client.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.minimax.io/v1/models",
                    headers={"Authorization": f"Bearer {key_value}"},
                )
                ok = resp.status_code == 200
                error = None if ok else f"HTTP {resp.status_code}"
        elif key_name == "AGENTS_INFRA_API_KEY":
            url = body.get("url", "http://agents-gateway:18892")
            async with httpx_client.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{url}/health",
                    headers={"x-api-key": key_value},
                )
                ok = resp.status_code == 200
                error = None if ok else f"HTTP {resp.status_code}"
        elif key_name in ("SERPER_API_KEY", "JINA_API_KEY", "TAVILY_API_KEY"):
            return {"ok": True, "latency_ms": 0, "note": "MCP keys validated on restart"}
        else:
            return JSONResponse({"error": f"Unknown key: {key_name}"}, status_code=400)

        latency = int((time.time() - start) * 1000)
        if ok:
            return {"ok": True, "latency_ms": latency}
        return {"ok": False, "error": error, "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "error": str(e)}
