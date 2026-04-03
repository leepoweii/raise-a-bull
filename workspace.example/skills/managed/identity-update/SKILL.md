---
name: identity-update
description: 重新編譯 IDENTITY.md。當你寫入或修改 identity/local/ 中的檔案後使用此 skill。
---

# Identity Update

重新編譯 `IDENTITY.md`，將 `identity/managed/` 和 `identity/local/` 的內容合併為 OpenClaw 讀取的單一檔案。

---

## 何時使用

- 寫入或修改了 `identity/local/` 中的檔案之後（例如：使用者要求記住供應商資訊、本地 SOP、品牌風格）
- 刪除了 `identity/local/` 中的檔案之後

## 何時不使用

- **對話產生的記憶**（開會決定、使用者偏好）→ 寫入 `memory/`，不是 identity
- **金門通用知識**（五鄉鎮、交通、氣候）→ 由 `feed.sh` 維護在 `identity/managed/`，永遠不要手動修改

---

## 資訊分類表

| 資訊類型 | 存放位置 | 範例 |
|---|---|---|
| 在地知識（長期不變） | `identity/local/` + 執行 identity-update | 供應商、SOP、品牌風格 |
| 互動記憶（對話產生） | `memory/` | 開會決定、使用者偏好 |
| 金門通用（系統維護） | `identity/managed/`（不要動） | 五鄉鎮、交通、氣候 |

---

## 執行步驟

### 1. 確認目錄存在

確認 `identity/managed/` 和 `identity/local/` 兩個目錄都存在。如果 `identity/local/` 不存在，建立它：

```bash
mkdir -p identity/local
```

### 2. 編譯 IDENTITY.md

使用 exec 工具執行：

```bash
echo '<!-- AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY. Source: identity/managed/ + identity/local/ -->' > IDENTITY.md
cat identity/managed/*.md >> IDENTITY.md
if ls identity/local/*.md &>/dev/null; then
  echo -e '\n---\n## 本地補充資料' >> IDENTITY.md
  cat identity/local/*.md >> IDENTITY.md
fi
```

### 3. 回報結果

統計檔案數量並回報：

> 已更新 IDENTITY.md（X 個 managed 檔 + Y 個 local 檔）

---

## 硬性規則

1. **永遠不要直接編輯 IDENTITY.md** — 它是編譯產物，下次編譯會覆蓋
2. **永遠不要修改 `identity/managed/` 中的檔案** — 由 `feed.sh` 系統維護
3. **只在 `identity/local/` 中新增或修改檔案**
4. **編譯順序固定**：managed 在前 → local 在後
5. **所有 identity 檔案使用 `.md` 副檔名**
