# bull.json Schema Spec

> Format: Spec docs (markdown), not JSON Schema. doctor.sh uses jq for field-presence + type checks.

## Purpose

`bull.json` is the identity card of a Bull instance. It records what this instance is, where it lives, what skills it has, and which paths are managed vs. unmanaged. Every script reads this file first to understand the instance it is operating on.

## Created By

- **raise.sh** -- generates on first `raise` from user-provided params + defaults.
- **feed.sh** -- updates `raise_a_bull_version`, `skills_version`, `skills_installed`, and `managed_paths` on feed.

## Field Table

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `instance_id` | string (kebab-case) | required | -- | Unique identifier for this instance. Must match `^[a-z0-9]+(-[a-z0-9]+)*$`. |
| `display_name` | string | required | -- | Human-readable name, typically Chinese (e.g. `"夢酒館"`). |
| `preset` | string enum | required | -- | One of: `bar`, `association`, `shop`, `office`. Determines default skill set. |
| `region` | string | required | `"kinmen"` | Deployment region. Currently only `kinmen` is supported. |
| `created_at` | string (ISO 8601) | required | -- | Timestamp when `raise.sh` first created this instance. |
| `workspace_root` | string (absolute path) | required | -- | Absolute path to the Bull workspace directory. |
| `raise_a_bull_version` | string (semver) | required | -- | Version of raise-a-bull repo at raise/feed time. Read from `VERSION` file. |
| `skills_version` | string | required | -- | Version tag of the skills bundle installed. |
| `skills_installed` | array of strings | required | `[]` | List of skill names currently installed (e.g. `["morning-review", "generate-content"]`). |
| `channels` | array of strings | required | `[]` | Active messaging channels. Values: `line`, `discord`. |
| `managed_paths` | array of strings | required | see below | Paths managed by raise-a-bull (overwritten on feed). |
| `unmanaged_paths` | array of strings | required | see below | Paths owned by the user (never overwritten). |

### Default `managed_paths`

```json
["skills/managed/", "identity/managed/", "managed-state.json", "IDENTITY.md"]
```

### Default `unmanaged_paths`

```json
["SOUL.md", "memory/", "skills/local/", "identity/local/", "secrets/"]
```

## Example JSON

```json
{
  "instance_id": "meng-bar",
  "display_name": "夢酒館",
  "preset": "bar",
  "region": "kinmen",
  "created_at": "2026-03-13T10:00:00+08:00",
  "workspace_root": "/Users/pwlee/Documents/Bulls/meng-bar",
  "raise_a_bull_version": "0.1.0",
  "skills_version": "0.1.0",
  "skills_installed": ["morning-review", "generate-content", "evening-review"],
  "channels": ["line"],
  "managed_paths": ["skills/managed/", "identity/managed/", "managed-state.json", "IDENTITY.md"],
  "unmanaged_paths": ["SOUL.md", "memory/", "skills/local/", "identity/local/", "secrets/"]
}
```

## Validation Rules (doctor.sh)

doctor.sh checks the following with jq:

1. **File exists** -- `bull.json` must be present at workspace root.
2. **Required fields present** -- All required fields must exist and not be `null`.
3. **Type checks:**
   - `instance_id` is a string matching `^[a-z0-9]+(-[a-z0-9]+)*$`
   - `display_name` is a non-empty string
   - `preset` is one of `"bar"`, `"association"`, `"shop"`, `"office"`
   - `region` is a string
   - `created_at` is a string (ISO 8601 format)
   - `workspace_root` is a string starting with `/`
   - `raise_a_bull_version` is a string
   - `skills_version` is a string
   - `skills_installed` is an array where every element is a string
   - `channels` is an array where every element is one of `"line"`, `"discord"`
   - `managed_paths` is an array of strings
   - `unmanaged_paths` is an array of strings
4. **Path check** -- `workspace_root` directory must exist on disk.
5. **No overlap** -- `managed_paths` and `unmanaged_paths` must not share entries.
