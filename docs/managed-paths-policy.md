# Managed Paths Policy

> 定義 workspace 中每個檔案/資料夾的擁有權與更新規則。

---

## 五類分類

| Category | 檔案 / 路徑 | 控制者 | feed.sh 行為 |
|---|---|---|---|
| **Managed** | `skills/managed/`, `identity/managed/`, `managed-state.json` | raise-a-bull repo | 更新（safe mode 跳過本地修改；`--force` 覆蓋） |
| **Compiled** | `IDENTITY.md` | feed.sh 自動合併 | 每次執行都重新編譯（從 `identity/managed/` + `identity/local/` 合併） |
| **User-owned** | `SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `memory/`, `skills/local/`, `identity/local/`, `params.json` | 使用者 | 永遠不動 |
| **Generated once** | `bull.json`, `docker-compose.yml`, `Dockerfile` | raise.sh 建立 | 永遠不覆蓋（除非刪除後重新 raise） |
| **Secrets** | `secrets/` | 使用者 | 永遠不動、永遠不備份、永遠不追蹤 |

---

## 詳細說明

### Managed — repo 控制的檔案

這些檔案由 raise-a-bull repo 提供，feed.sh 負責同步更新。

- `skills/managed/<skill-name>/SKILL.md` — 技能定義，repo 是唯一來源
- `identity/managed/*.md` — 區域身份資料（如 `facts.md`, `tone.md`）
- `managed-state.json` — 記錄版本、checksum、更新時間

**feed.sh 更新邏輯：**

1. **Safe mode**（預設）：比較 checksum，如果本地有修改則 SKIP（標記 `dirty: true`）
2. **Force mode**（`--force`）：無條件覆蓋，忽略本地修改
3. **Dry-run**（`--dry-run`）：只列出會改變的檔案，不實際執行

### Compiled — 自動合併的檔案

- `IDENTITY.md` — 由 `identity/managed/*.md` + `identity/local/*.md` 合併產生
- 標頭包含 `<!-- AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY -->`
- 每次 raise.sh 或 feed.sh 執行都會重新編譯

### User-owned — 使用者擁有的檔案

**任何 script 都不會修改這些檔案。**

| 檔案 | 用途 |
|---|---|
| `SOUL.md` | Bull 的人格與語氣設定 |
| `USER.md` | 使用者偏好（選填） |
| `TOOLS.md` | 工具使用說明 |
| `MEMORY.md` | 長期記憶摘要（選填） |
| `memory/` | 記憶資料夾 |
| `params.json` | 參數設定（brand、timezone 等） |
| `skills/local/` | 使用者自建技能 |
| `identity/local/` | 使用者自訂身份補充 |

### Generated once — 一次性產生

- `bull.json` — instance 的身份證，raise.sh 建立，feed.sh 只讀取不覆蓋
- `docker-compose.yml` — Docker 部署設定，raise.sh 從 template 產生
- 如果需要重建，必須刪除整個 bull 目錄後重新 raise

### Secrets — 機密資料

- `secrets/` 目錄，權限設為 `700`
- 包含 `provider.env`（API keys）及其他憑證檔案
- **不備份**（backup.sh 明確排除）
- **不追蹤**（不進 git、不進 managed-state.json）
- 使用者必須自行管理與備份

---

## bull.json 中的宣告

`bull.json` 明確記錄兩個陣列：

```json
{
  "managed_paths": ["skills/managed/", "identity/managed/", "managed-state.json", "IDENTITY.md"],
  "unmanaged_paths": ["SOUL.md", "memory/", "skills/local/", "identity/local/", "secrets/"]
}
```

AI agent 或 script 應以此為權威來源，判斷哪些路徑可以觸碰。
