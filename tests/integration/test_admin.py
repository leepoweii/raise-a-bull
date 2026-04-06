"""Integration tests for admin dashboard."""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context").mkdir()
    (workspace / "skills").mkdir()
    (workspace / "heartbeat").mkdir()
    (workspace / "config").mkdir()
    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    app = create_admin_app(db_path=db_path, workspace_dir=str(workspace))
    return app


@pytest_asyncio.fixture
async def client(admin_app):
    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/admin", admin_app)
    async with AsyncClient(
        transport=ASGITransport(app=parent),
        base_url="http://test",
    ) as c:
        yield c


async def _login(client: AsyncClient) -> AsyncClient:
    resp = await client.post("/admin/api/auth", json={"password": "testpass123"})
    assert resp.status_code == 200
    return client


class TestAuth:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        resp = await client.post("/admin/api/auth", json={"password": "testpass123"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "rab_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        resp = await client.post("/admin/api/auth", json={"password": "wrong"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_without_auth(self, client):
        resp = await client.get("/admin/api/context")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_with_auth(self, client):
        await _login(client)
        resp = await client.get("/admin/api/context")
        assert resp.status_code == 200


class TestContext:
    @pytest.mark.asyncio
    async def test_list_context_empty(self, client):
        await _login(client)
        resp = await client.get("/admin/api/context")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_write_and_read_context(self, client, admin_app):
        await _login(client)
        resp = await client.put("/admin/api/context/test.md", json={"content": "# Test\nHello"})
        assert resp.status_code == 200
        resp = await client.get("/admin/api/context/test.md")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Test\nHello"
        resp = await client.get("/admin/api/context")
        assert len(resp.json()) == 1
        assert resp.json()[0]["filename"] == "test.md"

    @pytest.mark.asyncio
    async def test_context_path_traversal_blocked(self, client):
        await _login(client)
        # httpx normalizes ../ in URLs before sending, so traversal never reaches the handler
        # Both 400 (caught by validator) and 404 (route not matched) mean "blocked"
        resp = await client.get("/admin/api/context/../../../etc/passwd")
        assert resp.status_code in (400, 404)

    @pytest.mark.asyncio
    async def test_context_non_md_blocked(self, client):
        await _login(client)
        resp = await client.put("/admin/api/context/test.py", json={"content": "hack"})
        assert resp.status_code == 400


class TestSkills:
    @pytest.mark.asyncio
    async def test_list_skills_empty(self, client):
        await _login(client)
        resp = await client.get("/admin/api/skills")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_read_write_skill(self, client, admin_app):
        await _login(client)
        workspace = admin_app.state.workspace_dir
        skill_dir = Path(workspace) / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Test Skill")
        resp = await client.get("/admin/api/skills/test-skill")
        assert resp.status_code == 200
        assert "# Test Skill" in resp.json()["content"]
        resp = await client.put("/admin/api/skills/test-skill", json={"content": "# Updated"})
        assert resp.status_code == 200
        resp = await client.get("/admin/api/skills/test-skill")
        assert resp.json()["content"] == "# Updated"


class TestHeartbeatViewer:
    @pytest.mark.asyncio
    async def test_get_heartbeat_empty(self, client):
        await _login(client)
        resp = await client.get("/admin/api/heartbeat")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert "last_run" in data
        assert "raw_markdown" in data
        assert data["tasks"] == []
        assert data["raw_markdown"] == ""

    @pytest.mark.asyncio
    async def test_write_and_read_heartbeat(self, client):
        await _login(client)
        content = "## Daily\n- [morning-report] Check inventory"
        resp = await client.put("/admin/api/heartbeat", json={"content": content})
        assert resp.status_code == 200
        resp = await client.get("/admin/api/heartbeat")
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_id"] == "morning-report"
        assert data["raw_markdown"] == content  # raw markdown preserved

    @pytest.mark.asyncio
    async def test_heartbeat_roundtrip_raw_markdown(self, client):
        await _login(client)
        content = "## Weekly\n- [trends] Update market trends\n<!-- - [disabled-task] This is disabled -->"
        resp = await client.put("/admin/api/heartbeat", json={"content": content})
        assert resp.status_code == 200
        resp = await client.get("/admin/api/heartbeat")
        data = resp.json()
        assert data["raw_markdown"] == content
        assert len(data["tasks"]) == 2
        assert data["tasks"][0]["task_id"] == "trends"
        assert data["tasks"][0]["enabled"] is True
        assert data["tasks"][1]["task_id"] == "disabled-task"
        assert data["tasks"][1]["enabled"] is False


class TestCredentials:
    @pytest.mark.asyncio
    async def test_credentials_crud(self, client):
        await _login(client)
        resp = await client.post("/admin/api/credentials", json={
            "key_name": "TEST_KEY", "key_value": "secret123", "service": "test"
        })
        assert resp.status_code == 200
        # Verify full POST response shape
        post_data = resp.json()
        assert "id" in post_data
        assert "key_name" in post_data
        assert "service" in post_data
        assert "created_at" in post_data
        assert post_data["key_name"] == "TEST_KEY"
        cred_id = post_data["id"]
        resp = await client.get("/admin/api/credentials")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert "***" in items[0]["key_value"]
        resp = await client.get(f"/admin/api/credentials/{cred_id}/reveal")
        assert resp.json()["key_value"] == "secret123"
        resp = await client.delete(f"/admin/api/credentials/{cred_id}")
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_credentials_test_unknown_key(self, client):
        await _login(client)
        resp = await client.post("/admin/api/credentials/test", json={
            "key_name": "UNKNOWN_KEY", "key_value": "xxx"
        })
        assert resp.status_code == 400


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_settings_defaults(self, client):
        await _login(client)
        resp = await client.get("/admin/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {"agent_name", "model", "max_steps", "auto_reply_timeout", "session_idle_timeout", "heartbeat_interval", "buffer_time", "nightly_compact_hour", "line_trigger_prefix"}
        assert set(data.keys()) == expected_keys
        for key, val in data.items():
            assert isinstance(val, str), f"Setting {key} should be string, got {type(val)}"

    @pytest.mark.asyncio
    async def test_put_settings(self, client, admin_app):
        await _login(client)
        resp = await client.put("/admin/api/settings", json={"agent_name": "TestBot", "model": "MiniMax-M2.5"})
        assert resp.status_code == 200
        resp = await client.get("/admin/api/settings")
        data = resp.json()
        assert data["agent_name"] == "TestBot"
        assert data["model"] == "MiniMax-M2.5"
        config_path = Path(admin_app.state.workspace_dir) / "config" / "settings.json"
        assert config_path.exists()

    @pytest.mark.asyncio
    async def test_settings_put_persists_all_fields(self, client):
        await _login(client)
        new_settings = {
            "agent_name": "TestBot",
            "model": "MiniMax-M2.5",
            "max_steps": "50",
            "auto_reply_timeout": "60",
            "session_idle_timeout": "900",
            "heartbeat_interval": "600",
        }
        resp = await client.put("/admin/api/settings", json=new_settings)
        assert resp.status_code == 200
        resp = await client.get("/admin/api/settings")
        data = resp.json()
        for key, expected in new_settings.items():
            assert data[key] == expected, f"Setting {key}: expected {expected}, got {data[key]}"


class TestPermissions:
    @pytest.mark.asyncio
    async def test_get_permissions_defaults(self, client):
        await _login(client)
        resp = await client.get("/admin/api/permissions")
        assert resp.status_code == 200
        data = resp.json()
        assert "role_mappings" in data
        assert "channel_config" in data
        assert len(data["role_mappings"]) > 0

    @pytest.mark.asyncio
    async def test_put_permissions(self, client, admin_app):
        await _login(client)
        new_perms = {
            "role_mappings": [{"discord_role": "Admin", "erp_role": "admin"}],
            "channel_config": [{"channel_name": "general", "role_ceiling": "admin"}],
        }
        resp = await client.put("/admin/api/permissions", json=new_perms)
        assert resp.status_code == 200
        resp = await client.get("/admin/api/permissions")
        data = resp.json()
        assert len(data["role_mappings"]) == 1
        assert data["role_mappings"][0]["discord_role"] == "Admin"

    @pytest.mark.asyncio
    async def test_discord_roles_no_bot(self, client):
        await _login(client)
        resp = await client.get("/admin/api/permissions/discord-roles")
        assert resp.status_code == 200
        assert resp.json()["available"] is False


class TestModels:
    @pytest.mark.asyncio
    async def test_list_models_fallback(self, client):
        await _login(client)
        resp = await client.get("/admin/api/models")
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) > 0
        assert any(m["id"] == "MiniMax-M2.7" for m in models)

    @pytest.mark.asyncio
    async def test_list_models_custom_override(self, client, admin_app):
        await _login(client)
        config_dir = Path(admin_app.state.workspace_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "models.json").write_text(json.dumps([
            {"id": "custom-model", "name": "Custom Model"},
        ]))
        resp = await client.get("/admin/api/models")
        models = resp.json()
        assert len(models) == 1
        assert models[0]["id"] == "custom-model"


class TestCacheHeaders:
    @pytest.mark.asyncio
    async def test_static_html_has_no_cache(self, client):
        resp = await client.get("/admin/")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("cache-control", "")

    @pytest.mark.asyncio
    async def test_static_js_has_no_cache(self, client):
        resp = await client.get("/admin/app.js")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("cache-control", "")

    @pytest.mark.asyncio
    async def test_static_css_has_no_cache(self, client):
        resp = await client.get("/admin/style.css")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("cache-control", "")
