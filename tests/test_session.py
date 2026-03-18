import pytest
import pytest_asyncio
from raisebull.session import SessionStore

@pytest_asyncio.fixture
async def store(tmp_path):
    s = SessionStore(str(tmp_path / "test.db"))
    await s.init()
    yield s
    await s.close()

@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("discord:999") is None

@pytest.mark.asyncio
async def test_save_and_get(store):
    await store.save("line:U123", session_id="s1", domain="line", token_count=100)
    row = await store.get("line:U123")
    assert row["session_id"] == "s1"
    assert row["domain"] == "line"
    assert row["token_count"] == 100

@pytest.mark.asyncio
async def test_clear(store):
    await store.save("line:U123", session_id="s1", domain="line", token_count=0)
    await store.clear("line:U123")
    assert await store.get("line:U123") is None
