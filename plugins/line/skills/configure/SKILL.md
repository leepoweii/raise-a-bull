---
name: configure
description: Configure LINE channel plugin — set tokens, tunnel URL
---

## Commands

### `/line:configure token`
Set LINE channel credentials. You need:
1. **Channel Secret** — from LINE Developer Console → Channel settings → Basic settings
2. **Channel Access Token** — from LINE Developer Console → Messaging API → Channel access token (long-lived)

Credentials are stored in `~/.claude/channels/line/.env` (chmod 600).

### `/line:configure tunnel <URL>`
Set a custom tunnel URL instead of the auto-generated cloudflared tunnel.
Useful if you have your own domain or use ngrok.
