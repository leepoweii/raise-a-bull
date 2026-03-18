# managed-state.json Schema Spec

> Format: Spec docs (markdown), not JSON Schema. doctor.sh uses jq for field-presence + type checks.

## Purpose

`managed-state.json` tracks the current state of managed content in a Bull instance -- which version of raise-a-bull and skills are deployed, when the last operations ran, and per-skill integrity data. This enables `feed.sh` to perform incremental updates and `doctor.sh` to detect drift.

## Created By

- **raise.sh** -- generates initial file on first raise.
- **feed.sh** -- updates version fields, timestamps, and per-skill entries on each feed.
- **backup.sh** -- updates `last_backup_at` after successful backup.
- **doctor.sh** -- reads only; never writes.

## Field Table

### Top-level

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `raise_a_bull_version` | string (semver) | required | -- | Version of raise-a-bull repo at the time of last raise or feed. Read from `VERSION` file. |
| `skills_bundle_version` | string | required | -- | Version of the skills bundle deployed. |
| `last_raise_at` | string (ISO 8601) | required | -- | Timestamp of the most recent `raise.sh` execution. |
| `last_feed_at` | string (ISO 8601) or null | required | `null` | Timestamp of the most recent `feed.sh` execution. `null` if never fed. |
| `last_backup_at` | string (ISO 8601) or null | required | `null` | Timestamp of the most recent `backup.sh` execution. `null` if never backed up. |
| `managed_skills` | object | required | `{}` | Map of skill name to skill state. Keys are skill names (kebab-case strings). |

### `managed_skills.<skill-name>` (per-skill entry)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `version` | string | required | -- | Version of this skill as deployed. |
| `checksum` | string (sha256) | required | -- | SHA-256 hash of the skill's `SKILL.md` file content. Used for drift detection. |
| `updated_at` | string (ISO 8601) | required | -- | Timestamp when this skill was last written by feed.sh. |
| `dirty` | boolean | required | `false` | `true` if doctor.sh detects the on-disk file has been modified since last feed (checksum mismatch). |

## Example JSON

```json
{
  "raise_a_bull_version": "0.1.0",
  "skills_bundle_version": "0.1.0",
  "last_raise_at": "2026-03-13T10:00:00+08:00",
  "last_feed_at": "2026-03-14T09:30:00+08:00",
  "last_backup_at": null,
  "managed_skills": {
    "morning-review": {
      "version": "0.1.0",
      "checksum": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "updated_at": "2026-03-14T09:30:00+08:00",
      "dirty": false
    },
    "generate-content": {
      "version": "0.1.0",
      "checksum": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
      "updated_at": "2026-03-14T09:30:00+08:00",
      "dirty": true
    }
  }
}
```

## Validation Rules (doctor.sh)

doctor.sh checks the following with jq:

1. **File exists** -- `managed-state.json` must be present at workspace root.
2. **Required fields present** -- All top-level required fields must exist.
3. **Type checks:**
   - `raise_a_bull_version` is a non-empty string
   - `skills_bundle_version` is a non-empty string
   - `last_raise_at` is a non-empty string (ISO 8601)
   - `last_feed_at` is a string or `null`
   - `last_backup_at` is a string or `null`
   - `managed_skills` is an object
4. **Per-skill entry checks** (for each key in `managed_skills`):
   - Key matches `^[a-z0-9]+(-[a-z0-9]+)*$` (kebab-case)
   - `version` is a non-empty string
   - `checksum` is a string matching `^[a-f0-9]{64}$` (sha256 hex)
   - `updated_at` is a non-empty string (ISO 8601)
   - `dirty` is a boolean
5. **Drift detection** (separate doctor.sh check, not just schema validation):
   - For each skill in `managed_skills`, compute `sha256sum` of the on-disk `SKILL.md` file.
   - Compare against stored `checksum`.
   - If mismatch and `dirty` is `false`, doctor.sh reports a warning: skill has been modified outside of feed.sh.
   - If the on-disk file is missing entirely, doctor.sh reports an error.
6. **Cross-file consistency:**
   - `raise_a_bull_version` should match `bull.json`'s `raise_a_bull_version`.
   - Skills listed in `managed_skills` should be a subset of `bull.json`'s `skills_installed`.
   - Mismatches are warnings, not errors (feed.sh may not have run yet after a bull.json update).
