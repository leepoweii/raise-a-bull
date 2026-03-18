# Minimum Ops Baseline

> 定義「健康」的 bull 長什麼樣、更新前後的檢查清單、故障排除流程。

---

## 什麼是「健康」的 Bull

「健康」= `doctor.sh` 的 10 項檢查全部通過（0 FAIL）。

| # | 檢查名稱 | 健康標準 |
|---|---|---|
| 1 | `workspace_structure` | bull.json、params.json 存在；secrets/、skills/managed/、skills/local/、memory/、identity/managed/、identity/local/ 目錄存在 |
| 2 | `file_permissions` | workspace 可寫；secrets/ 不是 world-readable |
| 3 | `bull_json_validation` | JSON 格式正確；必填欄位齊全；preset 值合法；instance_id 格式正確 |
| 4 | `params_json_validation` | JSON 格式正確；brand.name 存在；timezone 有設定 |
| 5 | `managed_state_json` | JSON 格式正確；managed_skills 的 key 與磁碟上的 skills/managed/ 目錄一致 |
| 6 | `managed_skills` | 每個 managed skill 都有 SKILL.md；沒有同名 skill 同時存在 managed/ 和 local/ |
| 7 | `secrets_readiness` | preset 要求的 integration 對應的 secrets 都已設定 |
| 8 | `runtime_availability` | Docker 可用且容器在跑（Docker mode），或 openclaw 在 PATH 中（native mode） |
| 9 | `port_availability` | 設定的 port 沒有被其他程式佔用 |
| 10 | `ops_readiness` | sanitize.sh、backup.sh 可執行；有至少一次備份紀錄 |

---

## Pre-Update Checklist（更新前）

在執行 feed.sh 更新 managed 檔案之前：

```bash
# 1. 備份
./scripts/backup.sh ~/bulls/<instance-id>

# 2. Dry-run — 檢查會改變什麼
./scripts/feed.sh --dry-run ~/bulls/<instance-id>

# 3. 確認 dry-run 結果合理後，執行更新
./scripts/feed.sh ~/bulls/<instance-id>
```

**注意事項：**
- feed.sh safe mode 會自動跳過本地修改過的 managed files
- 如果 dry-run 顯示 SKIP，表示該檔案有本地修改
- 只有確認要覆蓋本地修改時才用 `--force`

---

## Post-Deploy Checklist（部署後）

新 raise 或 feed 完成後：

```bash
# 1. 健康檢查
./scripts/doctor.sh ~/bulls/<instance-id>

# 2. 安全掃描
./scripts/sanitize.sh ~/bulls/<instance-id>/workspace/skills

# 3. 手動測試 2 個技能
#    - 挑一個核心技能（如 calendar-manager）
#    - 挑一個選填技能（如 weather-cwa）
#    - 確認技能可正常回應
```

**通過標準：**
- doctor.sh 回報 0 FAIL
- sanitize.sh 回報 0 issues
- 2 個技能測試都正常回應

---

## Troubleshooting 故障排除

### 流程

```
1. 跑 doctor.sh
   ↓
2. 先修 FAIL（必修）
   ↓
3. 再修 WARN（建議修）
   ↓
4. 全部 OK → 完成
```

### 常見問題對照表

| 檢查 # | 狀態 | 常見原因 | 解法 |
|---|---|---|---|
| 1 | FAIL | 目錄結構不完整 | 重新 raise 或手動 `mkdir -p` 缺少的目錄 |
| 2 | WARN | secrets/ 權限太開放 | `chmod 700 workspace/secrets/` |
| 3 | FAIL | bull.json 損壞或欄位缺失 | 對照 `schemas/bull.spec.md` 手動修復 |
| 4 | FAIL | params.json 缺少 brand.name | 編輯 params.json 加入必填欄位 |
| 5 | WARN | managed-state.json 與 skills 目錄不同步 | 執行 feed.sh 重新同步 |
| 6 | FAIL | managed skill 缺少 SKILL.md | 執行 feed.sh 補回，或檢查 repo 中的 skill 是否完整 |
| 7 | FAIL/WARN | API key 未設定 | 填寫 `secrets/provider.env`（見 `docs/accounts-checklist.md`） |
| 8 | FAIL | Docker 未安裝或容器未啟動 | 安裝 Docker 或 `docker compose up -d` |
| 9 | FAIL | Port 被佔用 | 換 port 或停掉佔用的程式 |
| 10 | WARN | 未執行過備份 | `./scripts/backup.sh ~/bulls/<instance-id>` |

### Managed / Local 邊界問題

如果你不確定某個檔案該不該改：

1. 查看 `bull.json` 的 `managed_paths` 和 `unmanaged_paths`
2. 在 `managed_paths` 裡的 → 由 repo 控制，改了會被 feed.sh 覆蓋
3. 在 `unmanaged_paths` 裡的 → 使用者控制，script 不會動
4. `IDENTITY.md` 比較特殊 — 是 compiled 檔案，每次 feed 都會重建

詳細分類見 `docs/managed-paths-policy.md`。
