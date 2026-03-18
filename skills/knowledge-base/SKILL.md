---
name: knowledge-base
description: Use when someone wants to remember, look up, update, or delete stored knowledge entries (SOPs, facts, operational notes, etc.) in the knowledge base.
---

# knowledge-base

知識庫的完整 CRUD 操作：新增、查詢、更新、刪除。

## 設定

讀取 `../../params.json` 的 `backend.url` 作為 `{BACKEND_URL}`。

## 認證

所有 API 呼叫前，先取得 bearer token：

```
POST {BACKEND_URL}/auth/login
```

後續請求皆帶 `Authorization: Bearer {JWT_TOKEN}`。

---

## 操作

### 1. 新增知識（CREATE）

**觸發時機**：使用者說「記住」、「儲存」、「新增」知識。

**流程**：

1. 先向使用者確認要記住的內容
2. 使用者確認後，呼叫 API

**API**：

```
POST {BACKEND_URL}/knowledge
Authorization: Bearer {JWT_TOKEN}
Content-Type: application/json

{
  "entity": "store_hours",
  "aliases": ["營業時間", "opening hours"],
  "content": "週一至週五 09:00-18:00"
}
```

**參數**：

- `entity` (string, required)：實體名稱（小寫，空格替換為底線）
- `content` (string, required)：要記住的內容
- `aliases` (array of strings, required)：別名列表

**確認流程**：

收到使用者的知識後，先回覆確認：

```
請確認要記住以下知識：
- 實體：{entity}
- 別名：{aliases}
- 內容：{content}

回覆「確認」以儲存
```

使用者確認後才呼叫 API。

**回應**：

- 成功：「已記住 "{entity}"」
- 已存在：「已存在，請使用更新功能修改」

---

### 2. 查詢知識（READ）

**觸發時機**：使用者問「查詢」、「搜尋」、「找」某個知識。

**API**：

```
# 查詢單一條目
GET {BACKEND_URL}/knowledge/{entity}
Authorization: Bearer {JWT_TOKEN}

# 列出所有條目
GET {BACKEND_URL}/knowledge
Authorization: Bearer {JWT_TOKEN}
```

**回覆範本**：

```
{entity}
{content}

別名：{aliases}
```

**回應**：

- 找不到：「找不到相關知識，可以使用新增功能加入」
- 知識庫為空：「目前知識庫沒有任何條目」

---

### 3. 更新知識（UPDATE）

**觸發時機**：使用者說「更新」、「修改」、「變更」某個知識。

**API**：

```
PATCH {BACKEND_URL}/knowledge/{entity}
Authorization: Bearer {JWT_TOKEN}
Content-Type: application/json

{
  "content": "新內容",
  "aliases": ["新別名1", "新別名2"]
}
```

至少要提供 `content` 或 `aliases` 其中一個。

**回應**：

- 成功：「已更新 "{entity}"」
- 404：「找不到 "{entity}"，請先新增」

---

### 4. 刪除知識（DELETE）

**觸發時機**：使用者說「刪除」、「移除」、「忘記」某個知識。

**API**：

```
DELETE {BACKEND_URL}/knowledge/{entity}
Authorization: Bearer {JWT_TOKEN}
```

**回應**：

- 成功：「已刪除 "{entity}"」
- 404：「找不到 "{entity}"，無法刪除」

---

## 重要規則

- **必須呼叫後端 API**，不要讀寫本地檔案
- 新增前必須經過使用者確認
- `{BACKEND_URL}` 從 `../../params.json` 的 `backend.url` 取得，不要硬編碼
