# GUIDE.md — raise-a-bull Agent Deployment Protocol

> If you are a fresh AI agent entering this repository for the first time:
> 1. Read this GUIDE.md fully before acting.
> 2. Treat `scripts/` and `schemas/` as the source of truth.
> 3. Default to Docker-first deployment unless explicitly told otherwise.
> 4. Never write secrets into tracked files.
> 5. Never modify user-owned files (`SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `memory/`).
> 6. Never edit `IDENTITY.md` directly — it is compiled from `identity/managed/` + `identity/local/`.
> 7. Use `doctor.sh` to validate every deployment or update.
> 8. When uncertain, stop and report the ambiguity instead of improvising.

---

## 0. Mission

**raise-a-bull** 是一個部署工具包，用來為金門地方組織生成 AI 辦公室助理（稱為「Bull」）。每頭 Bull 是一個 OpenClaw instance，具備預設技能、在地身份、以及可自訂的人格。Agent 的工作是**正確地 raise（部署）一頭新 Bull，或 feed（更新）一頭既有的 Bull**。Agent 不應該修改 repo 本身的程式碼、不應該自行發明 skill 格式、不應該碰使用者擁有的檔案。

---

## 1. Success Criteria

部署完成的判定條件：

1. `bull.json` 存在且通過 `schemas/bull.spec.md` 的驗證規則
2. `doctor.sh` 執行結果為 **0 FAIL**
3. 使用者已被告知下一步（填 secrets、啟動服務）

更新完成的判定條件：

1. `feed.sh` 執行成功（無 error exit）
2. `doctor.sh` 執行結果為 **0 FAIL**
3. 使用者已被告知變更摘要（NEW / UPDATED / SKIPPED 數量）

---

## 2. Hard Rules / Guardrails

1. **永遠不要**把 API key、token、password 寫進 git 追蹤的檔案
2. **永遠不要**修改 user-owned 檔案：`SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `memory/`, `skills/local/`, `identity/local/`, `params.json`
3. **永遠不要**直接編輯 `IDENTITY.md` — 它是由 `identity/managed/` + `identity/local/` 自動合併產生的
4. **永遠不要**刪除 `secrets/` 目錄或其內容
5. **永遠不要**在沒有 `--dry-run` 確認的情況下直接執行 `feed.sh --force`
6. **必須**在每次部署或更新後執行 `doctor.sh`
7. **必須**在更新前執行 `backup.sh`
8. **必須**使用 `bull.json` 中的 `managed_paths` / `unmanaged_paths` 判斷檔案擁有權
9. **必須**遵守 preset 定義的 skill 組合（`presets/*.json`），不自行增減 managed skills
10. **必須**使用 kebab-case 作為 instance-id（e.g. `peili-station`，而非 `培力站`）

---

## 3. Files and Roles

### Repo 目錄結構

| 路徑 | 職責 |
|---|---|
| `VERSION` | 語意版號（目前 `0.1.0`） |
| `schemas/` | 規格文件：`bull.spec.md`, `params.spec.md`, `managed-state.spec.md` |
| `presets/` | 預設組合包：`bar.json`, `association.json`, `shop.json`, `office.json` |
| `skills/` | 技能模組來源（每個技能一個資料夾，內含 `SKILL.md`） |
| `identity/regions/` | 區域身份資料（目前只有 `kinmen/`） |
| `identity/templates/` | 身份模板（`SOUL.md.template`, `TOOLS.md.template`） |
| `templates/` | Docker 部署模板（`Dockerfile`, `docker-compose.yml.template`, `.env.example`） |
| `scripts/` | CLI 工具（見下方） |
| `docs/` | 操作文件 |

### Workspace 目錄結構（部署後的 Bull）

```
~/bulls/<instance-id>/
├── docker-compose.yml        # Generated once（Docker mode）
├── Dockerfile                 # Generated once（Docker mode）
├── workspace/
│   ├── bull.json              # Generated once — instance 身份證
│   ├── params.json            # User-owned — 參數設定
│   ├── managed-state.json     # Managed — 版本與 checksum 狀態
│   ├── IDENTITY.md            # Compiled — 自動合併產生
│   ├── SOUL.md                # User-owned — 人格設定
│   ├── TOOLS.md               # User-owned — 工具說明
│   ├── skills/
│   │   ├── managed/           # Managed — repo 控制的技能
│   │   └── local/             # User-owned — 使用者自建技能
│   ├── identity/
│   │   ├── managed/           # Managed — repo 控制的身份資料
│   │   └── local/             # User-owned — 使用者自訂身份
│   ├── memory/                # User-owned — 記憶資料
│   └── secrets/               # User-owned — 機密資料（chmod 700）
│       ├── .env.example       # 範例檔
│       └── provider.env       # 使用者填寫的 API keys
```

### 檔案分類速查

| 分類 | 檔案 | feed.sh 行為 |
|---|---|---|
| Managed | `skills/managed/`, `identity/managed/`, `managed-state.json` | 更新（safe/force） |
| Compiled | `IDENTITY.md` | 每次重新編譯 |
| User-owned | `SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `memory/`, `skills/local/`, `identity/local/`, `params.json` | 永不觸碰 |
| Generated once | `bull.json`, `docker-compose.yml` | 永不覆蓋 |
| Secrets | `secrets/` | 永不觸碰、不備份 |

完整說明見 `docs/managed-paths-policy.md`。

---

## 4. Deployment Modes

### Docker Mode（預設，推薦）

```bash
./scripts/raise.sh --preset association --name "peili-station" --port 18890
```

- 產生 `docker-compose.yml` 和 `Dockerfile`
- 啟動方式：`cd ~/bulls/<instance-id> && docker compose up -d`
- 適合正式部署

### Native Mode

```bash
./scripts/raise.sh --preset association --name "peili-station" --port 18890 --native
```

- 不產生 Docker 檔案
- 啟動方式：`openclaw gateway --workspace <workspace-path> --port <port>`
- 適合開發與 debug

### AI Agent 行為規則

- **預設使用 Docker mode**，除非使用者明確指定 `--native`
- Docker mode 下，確認 `docker` command 可用再繼續
- Native mode 下，確認 `openclaw` command 可用再繼續
- 兩種 mode 的 workspace 結構完全相同，差別只在啟動方式

---

## 5. Standard Deployment Workflow

### Step 1 — 確認需求

向使用者確認三項必要資訊：

| 參數 | 說明 | 範例 |
|---|---|---|
| `--preset` | 預設組合包（`bar`, `association`, `shop`, `office`） | `association` |
| `--name` | 顯示名稱（ASCII）或搭配 `--instance-id` | `"peili-station"` |
| `--port` | Gateway port（預設 18888） | `18890` |

如果 `--name` 包含中文，必須同時提供 `--instance-id`（kebab-case）。

### Step 2 — 檢查前置條件

```bash
# Docker mode
command -v docker && command -v git && command -v jq

# Native mode
command -v openclaw && command -v git && command -v jq
```

### Step 3 — Clone repo

```bash
git clone https://github.com/leepoweii/raise-a-bull.git
cd raise-a-bull
```

如果 repo 已存在，確認是最新版：

```bash
cd raise-a-bull && git pull
```

### Step 4 — 執行 raise.sh

```bash
./scripts/raise.sh --preset association --name "peili-station" --port 18890
```

raise.sh 會自動執行 12 個步驟：
1. 建立 workspace 目錄結構
2. 安裝 preset 指定的 skills
3. 複製 identity region 檔案
4. 編譯 IDENTITY.md
5. 產生 SOUL.md（從 template）
6. 產生 TOOLS.md（從 template）
7. 產生 bull.json
8. 產生 params.json
9. 產生 managed-state.json
10. 複製 .env.example
11. 設定 Docker（或跳過 if native）
12. 執行 sanitize.sh + doctor.sh

### Step 5 — 填寫 secrets

```bash
cp ~/bulls/<instance-id>/workspace/secrets/.env.example \
   ~/bulls/<instance-id>/workspace/secrets/provider.env

# 編輯 provider.env，填入 API keys
```

需要哪些 key 取決於 preset，詳見 `docs/accounts-checklist.md`。

### Step 6 — 啟動服務

```bash
# Docker mode
cd ~/bulls/<instance-id> && docker compose up -d

# Native mode
openclaw gateway --workspace ~/bulls/<instance-id>/workspace --port 18890
```

### Step 7 — 驗證部署

```bash
./scripts/doctor.sh ~/bulls/<instance-id>
```

回報結果給使用者。0 FAIL = 部署成功。

---

## 6. Update Workflow

當 repo 有新版本的 skills 或 identity 時：

```bash
# 1. 更新 repo
cd raise-a-bull && git pull

# 2. 備份
./scripts/backup.sh ~/bulls/<instance-id>

# 3. Dry-run — 檢查會改什麼
./scripts/feed.sh --dry-run ~/bulls/<instance-id>

# 4. 執行更新
./scripts/feed.sh ~/bulls/<instance-id>

# 5. 健康檢查
./scripts/doctor.sh ~/bulls/<instance-id>

# 6. 回報結果
#    - NEW / UPDATED / SKIPPED 數量
#    - doctor.sh 結果
#    - 如果有 SKIP（本地修改），提醒使用者
```

**feed.sh 行為：**
- `--dry-run`：只列出變更，不執行
- 預設 safe mode：跳過本地修改的 managed files
- `--force`：覆蓋所有 managed files（包括本地修改的）

---

## 7. Troubleshooting Workflow

```
Step 1: 執行 doctor.sh
    ./scripts/doctor.sh ~/bulls/<instance-id>

Step 2: 先修 FAIL（系統無法正常運作）
    → 參照下方常見問題表

Step 3: 再修 WARN（非致命但建議處理）
    → 參照下方常見問題表

Step 4: 全部 OK → 完成
```

### 常見問題速查

| 檢查 | 問題 | 解法 |
|---|---|---|
| #1 workspace_structure | 目錄不完整 | 重新 raise 或 `mkdir -p` 缺少的目錄 |
| #2 file_permissions | secrets/ 權限太開放 | `chmod 700 workspace/secrets/` |
| #3 bull_json_validation | JSON 格式錯誤或欄位缺失 | 對照 `schemas/bull.spec.md` 修復 |
| #4 params_json_validation | 缺少 brand.name | 編輯 `params.json` 補上必填欄位 |
| #5 managed_state_json | skills 與 state 不同步 | 執行 `feed.sh` 重新同步 |
| #6 managed_skills | skill 缺少 SKILL.md | 執行 `feed.sh` 補回 |
| #7 secrets_readiness | API key 未設定 | 填寫 `secrets/provider.env` |
| #8 runtime_availability | Docker 未安裝或容器停了 | 安裝 Docker 或 `docker compose up -d` |
| #9 port_availability | Port 被佔用 | 換 port 或停掉佔用程式 |
| #10 ops_readiness | 未執行過備份 | `./scripts/backup.sh ~/bulls/<instance-id>` |

詳細說明見 `docs/minimum-ops-baseline.md`。

---

## 8. Output Format

AI agent 在每個步驟應回報：

```
## Step N: <步驟名稱>

**Before:** <執行前的狀態或準備動作>
**Action:** <實際執行的指令>
**Result:** OK / WARN / FAIL
**Details:** <補充說明（如有）>
```

範例：

```
## Step 4: raise.sh

**Before:** Confirmed preset=association, name=peili-station, port=18890
**Action:** ./scripts/raise.sh --preset association --name "peili-station" --port 18890
**Result:** OK
**Details:** 6 skills installed, workspace created at ~/bulls/peili-station/workspace
```

---

## 9. Machine-Checkable Checklist

部署後可用程式驗證的檢查清單：

```bash
# 以下每項都應通過（exit 0 或輸出符合預期）

# bull.json 存在且為合法 JSON
jq empty ~/bulls/<id>/workspace/bull.json

# bull.json 包含必填欄位
jq -e '.instance_id and .preset and .region and .created_at and .display_name' ~/bulls/<id>/workspace/bull.json

# params.json 存在且有 brand.name
jq -e '.brand.name' ~/bulls/<id>/workspace/params.json

# managed-state.json 存在且為合法 JSON
jq empty ~/bulls/<id>/workspace/managed-state.json

# IDENTITY.md 存在且包含 managed 內容
test -f ~/bulls/<id>/workspace/IDENTITY.md
grep -q 'AUTO-GENERATED' ~/bulls/<id>/workspace/IDENTITY.md

# SOUL.md 存在
test -f ~/bulls/<id>/workspace/SOUL.md

# skills/managed/ 有至少一個 skill
test -d ~/bulls/<id>/workspace/skills/managed/ && \
  ls ~/bulls/<id>/workspace/skills/managed/ | head -1

# secrets/ 權限正確
test -d ~/bulls/<id>/workspace/secrets/

# doctor.sh 通過（exit 0）
./scripts/doctor.sh ~/bulls/<id>
```

---

## 10. Escalation Rule

**遇到以下情況時，停止動作並回報給使用者：**

1. **Schema 不一致** — `bull.json` 或 `params.json` 的欄位與 `schemas/` 的 spec 衝突
2. **Secrets 無法取得** — 使用者未提供必要的 API key，且你無法自行取得
3. **Host 權限不足** — 無法建立目錄、無法 chmod、無法啟動 Docker
4. **Preset 不存在** — 使用者指定的 preset 不在 `presets/` 中（目前支援：`bar`, `association`, `shop`, `office`）
5. **Port 衝突** — 指定的 port 已被佔用，且使用者未指定替代方案
6. **Repo 版本問題** — `git pull` 有衝突，或 `VERSION` 檔案缺失
7. **超出 preset 能力範圍** — 使用者要求的功能不在 preset 的 skills 或 integrations 中
8. **user-owned 檔案損壞** — `SOUL.md` 或 `params.json` 格式錯誤，需要使用者自行修復

**原則：寧可停下來問，也不要猜測後行動。**
