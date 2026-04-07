"""Static-asset structural tests for the dashboard Settings page.

These tests guard against the bug where a key is added to `_ALLOWED_KEYS`
(making it round-trip via the API) but no form field is added to settings.html
(so users can't actually edit it). The dashboard frontend is hand-coded HTML,
NOT auto-rendered, so every registry entry needs an explicit `<input>` block.
"""
from pathlib import Path

import pytest

from raisebull.admin.routes_settings import _ALLOWED_KEYS

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_HTML = _PROJECT_ROOT / "src" / "raisebull" / "admin" / "static" / "pages" / "settings.html"
_SETTINGS_JS = _PROJECT_ROOT / "src" / "raisebull" / "admin" / "static" / "pages" / "settings.js"


@pytest.mark.parametrize("key", sorted(_ALLOWED_KEYS.keys()))
def test_settings_html_has_input_for_allowed_key(key: str):
    """Every key in _ALLOWED_KEYS must have a matching form field in settings.html.

    Without this, the API round-trips the value but the user has no UI to edit it —
    a silent UX gap that broke nightly_compact_threshold (and 3 pre-existing keys)
    until the static-inspection check in Phase 4 caught it.
    """
    html = _SETTINGS_HTML.read_text(encoding="utf-8")
    expected = f'x-model="settings.{key}"'
    assert expected in html, (
        f"settings.html is missing a form field for `{key}`. "
        f"Expected to find `{expected}`. "
        f"Every _ALLOWED_KEYS entry needs an <input>/<select> with the matching x-model "
        f"so users can edit it from the dashboard."
    )


@pytest.mark.parametrize("key", sorted(_ALLOWED_KEYS.keys()))
def test_settings_js_initial_state_includes_allowed_key(key: str):
    """settings.js initial state must include every _ALLOWED_KEYS entry.

    Alpine binds inputs to `this.settings.<key>` via x-model. If the initial state
    object lacks the key, Alpine still works (it adds the key on first edit), but
    the property isn't reactive in the strict pre-load window. Including all keys
    in the initial state makes Alpine bindings predictable and matches the API shape.
    """
    js = _SETTINGS_JS.read_text(encoding="utf-8")
    # Match `<key>:` inside the settings: { ... } object literal — flexible whitespace
    expected = f"{key}:"
    assert expected in js, (
        f"settings.js initial state is missing `{key}`. "
        f"Expected to find `{expected}` inside the `settings: {{ ... }}` object. "
        f"All _ALLOWED_KEYS entries should be initialized to '' so Alpine bindings "
        f"are reactive before the API load completes."
    )
