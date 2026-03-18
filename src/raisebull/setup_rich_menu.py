"""Setup LINE Rich Menu for raise-a-bull.

Run once after initial setup:
    docker compose run --rm daniu python -m raisebull.setup_rich_menu

Requires: LINE_CHANNEL_ACCESS_TOKEN in environment.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ASSETS_DIR = Path(__file__).parent / "assets"
RICH_MENU_IMAGE = ASSETS_DIR / "rich_menu.png"

LINE_API = "https://api.line.me/v2/bot"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_rich_menu(token: str) -> str:
    """Create rich menu definition, return richMenuId."""
    definition = {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": "raise-a-bull menu",
        "chatBarText": "選單",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "/new"},
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "/info"},
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "/compact"},
            },
        ],
    }
    resp = httpx.post(
        f"{LINE_API}/richmenu",
        headers={**_headers(token), "Content-Type": "application/json"},
        content=json.dumps(definition).encode(),
    )
    resp.raise_for_status()
    rich_menu_id = resp.json()["richMenuId"]
    print(f"✓ Created rich menu: {rich_menu_id}")
    return rich_menu_id


def upload_image(token: str, rich_menu_id: str) -> None:
    """Upload the PNG image to the rich menu."""
    image_data = RICH_MENU_IMAGE.read_bytes()
    resp = httpx.post(
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        headers={**_headers(token), "Content-Type": "image/png"},
        content=image_data,
        timeout=30,
    )
    resp.raise_for_status()
    print("✓ Uploaded rich menu image")


def set_default(token: str, rich_menu_id: str) -> None:
    """Set this rich menu as the default for all users."""
    resp = httpx.post(
        f"{LINE_API}/user/all/richmenu/{rich_menu_id}",
        headers=_headers(token),
        content=b"{}",
    )
    resp.raise_for_status()
    print("✓ Set as default rich menu for all users")


def delete_old_menus(token: str, keep_id: str) -> None:
    """Delete any previously created rich menus (clean slate)."""
    resp = httpx.get(f"{LINE_API}/richmenu/list", headers=_headers(token))
    resp.raise_for_status()
    menus = resp.json().get("richmenus", [])
    for menu in menus:
        mid = menu["richMenuId"]
        if mid != keep_id:
            httpx.delete(f"{LINE_API}/richmenu/{mid}", headers=_headers(token))
            print(f"  deleted old menu: {mid}")


def main() -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        print("ERROR: LINE_CHANNEL_ACCESS_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    print("Setting up LINE Rich Menu...")
    rich_menu_id = create_rich_menu(token)
    upload_image(token, rich_menu_id)
    set_default(token, rich_menu_id)
    delete_old_menus(token, keep_id=rich_menu_id)
    print("\nDone! Rich menu is live. Open LINE and check the bottom of the chat.")


if __name__ == "__main__":
    main()
