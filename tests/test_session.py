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


@pytest.mark.asyncio
async def test_update_tokens_success(store):
    await store.save("discord:42", session_id="s1", domain="discord", token_count=0)
    await store.update_tokens("discord:42", 999)
    row = await store.get("discord:42")
    assert row["token_count"] == 999


@pytest.mark.asyncio
async def test_update_tokens_missing_key_raises(store):
    with pytest.raises(KeyError):
        await store.update_tokens("nonexistent", 1)


@pytest.mark.asyncio
async def test_require_db_before_init_raises():
    s = SessionStore(":memory:")
    # init() has NOT been called — any method should raise RuntimeError
    with pytest.raises(RuntimeError):
        await s.get("any:key")


@pytest.mark.asyncio
async def test_save_with_name(store):
    """Session name is stored and retrievable."""
    await store.save("discord:42", session_id="s1", domain="discord", token_count=100, name="general")
    row = await store.get("discord:42")
    assert row["name"] == "general"


@pytest.mark.asyncio
async def test_save_without_name_preserves_existing(store):
    """Saving without name= preserves the existing name (doesn't overwrite to NULL)."""
    await store.save("discord:42", session_id="s1", domain="discord", token_count=100, name="general")
    # Update without name — should preserve "general"
    await store.save("discord:42", session_id="s2", domain="discord", token_count=200)
    row = await store.get("discord:42")
    assert row["session_id"] == "s2"
    assert row["token_count"] == 200
    assert row["name"] == "general"


@pytest.mark.asyncio
async def test_save_name_can_be_updated(store):
    """Passing a new name= overwrites the old one."""
    await store.save("discord:42", session_id="s1", domain="discord", token_count=100, name="old-name")
    await store.save("discord:42", session_id="s1", domain="discord", token_count=100, name="new-name")
    row = await store.get("discord:42")
    assert row["name"] == "new-name"
