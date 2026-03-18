# params.json Schema Spec

> Format: Spec docs (markdown), not JSON Schema. doctor.sh uses jq for field-presence + type checks.

## Purpose

`params.json` holds instance-specific configuration -- brand identity, API endpoints, weather settings, calendar/task integrations, and timezone. This is the user's main customization surface. Skills read from this file to personalize their behavior.

## Created By

- **User** -- fills in during `raise.sh` interactive setup or edits manually afterward.
- **raise.sh** -- generates a skeleton with defaults, prompts user for required fields.

## Field Table

### Top-level

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `brand` | object | required | -- | Brand identity settings. |
| `backend` | object | optional | `{}` | Backend API connection. |
| `weather` | object | optional | see below | Weather data settings. |
| `calendar` | object | optional | `{}` | Google Calendar integration. |
| `tasks` | object | optional | `{}` | Google Tasks integration. |
| `timezone` | string | optional | `"Asia/Taipei"` | IANA timezone for the instance. |

### `brand` (required)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `brand.name` | string | required | -- | Brand name in primary language (e.g. `"培力站"`). |
| `brand.name_en` | string | optional | -- | English brand name (e.g. `"Peili Station"`). |
| `brand.primary_color` | string (hex) | optional | -- | Primary brand color (e.g. `"#2D1B69"`). |
| `brand.accent_color` | string (hex) | optional | -- | Accent color (e.g. `"#F5A623"`). |
| `brand.font_cn` | string | optional | `"Noto Sans TC"` | Chinese font family. |
| `brand.font_en` | string | optional | -- | English font family. |
| `brand.location` | string | optional | -- | Physical location description (e.g. `"金門金城鎮"`). |

### `backend` (optional)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `backend.url` | string | optional | -- | Backend API base URL. Supports env var reference `${BACKEND_URL}`. |
| `backend.auth_endpoint` | string | optional | -- | Auth endpoint path (e.g. `"/auth/token"`). |

### `weather` (optional)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `weather.default_location` | string | optional | `"金城鎮"` | Default location for weather queries. |
| `weather.dataset` | string | optional | `"F-D0047-085"` | CWA open data dataset ID. |

### `calendar` (optional)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `calendar.account` | string | optional | -- | Google account email for calendar access. |
| `calendar.default_calendar` | string | optional | `"primary"` | Calendar ID to use by default. |
| `calendar.timezone` | string | optional | `"Asia/Taipei"` | Timezone for calendar events. |

### `tasks` (optional)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `tasks.default_list_id` | string | optional | -- | Google Tasks list ID for general tasks. |
| `tasks.focus_list_id` | string | optional | -- | Google Tasks list ID for daily-review focus items. |

## Example JSON

```json
{
  "brand": {
    "name": "培力站",
    "name_en": "Peili Station",
    "primary_color": "#2D1B69",
    "accent_color": "#F5A623",
    "font_cn": "Noto Sans TC",
    "font_en": "Inter",
    "location": "金門金城鎮"
  },
  "backend": {
    "url": "${BACKEND_URL}",
    "auth_endpoint": "/auth/token"
  },
  "weather": {
    "default_location": "金城鎮",
    "dataset": "F-D0047-085"
  },
  "calendar": {
    "account": "example@gmail.com",
    "default_calendar": "primary",
    "timezone": "Asia/Taipei"
  },
  "tasks": {
    "default_list_id": "MTIzNDU2Nzg5",
    "focus_list_id": "OTg3NjU0MzIx"
  },
  "timezone": "Asia/Taipei"
}
```

## Validation Rules (doctor.sh)

doctor.sh checks the following with jq:

1. **File exists** -- `params.json` must be present at workspace root.
2. **Required fields present:**
   - `brand` object must exist
   - `brand.name` must exist and be a non-empty string
3. **Type checks:**
   - `brand` is an object
   - `brand.name` is a string
   - `brand.name_en`, if present, is a string
   - `brand.primary_color` and `brand.accent_color`, if present, match `^#[0-9A-Fa-f]{6}$`
   - `brand.font_cn` and `brand.font_en`, if present, are strings
   - `brand.location`, if present, is a string
   - `backend`, if present, is an object
   - `backend.url`, if present, is a string
   - `backend.auth_endpoint`, if present, is a string
   - `weather`, if present, is an object
   - `weather.default_location` and `weather.dataset`, if present, are strings
   - `calendar`, if present, is an object
   - `calendar.account`, if present, is a string
   - `calendar.default_calendar`, if present, is a string
   - `calendar.timezone`, if present, is a string
   - `tasks`, if present, is an object
   - `tasks.default_list_id` and `tasks.focus_list_id`, if present, are strings
   - `timezone`, if present, is a string
4. **Env var references** -- `backend.url` value `${BACKEND_URL}` is valid; doctor.sh warns (not errors) if the referenced env var is unset.
5. **Defaults applied at runtime** -- doctor.sh does NOT inject defaults. Scripts apply defaults when reading. doctor.sh only validates what is present.
