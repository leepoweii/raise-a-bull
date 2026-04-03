"""Dashboard credentials CRUD + test API."""

import time

import httpx as httpx_client
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from raisebull.admin.crud import CrudTable

router = APIRouter(prefix="/api/credentials")


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
    return item


@router.put("/{cred_id}")
async def update_credential(cred_id: str, request: Request):
    body = await request.json()
    allowed = {"key_value", "service"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)
    item = _get_table(request).update(cred_id, data)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"ok": True}


@router.delete("/{cred_id}")
async def delete_credential(cred_id: str, request: Request):
    if _get_table(request).delete(cred_id):
        return {"ok": True}
    return JSONResponse({"error": "Not found"}, status_code=404)


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
