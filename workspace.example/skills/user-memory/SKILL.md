---
name: user-memory
description: 在 compact 時執行。整理對話中出現的每位成員，更新 memory/users/ 的個人記憶檔，並維護 MEMORY.md 的成員目錄。在 group chat 中可能有多位成員需要同時處理。
---

# user-memory

記住每位成員的個人資訊、偏好和互動歷史，讓小牛在未來對話中能更個人化地回應。

## 目錄結構

```
workspace/memory/
  MEMORY.md                     ← 成員目錄索引（每次都會載入）
  users/
    discord_123456789.md        ← 個人記憶（以 channel_userid 命名）
    line_Uabc123.md
```

## MEMORY.md 成員目錄格式

在 `MEMORY.md` 的 `## 成員目錄` 區塊維護下列表格：

```markdown
## 成員目錄

| channel | user_id | 稱呼 | 檔案 |
|---|---|---|---|
| discord | 123456789012345678 | 阿明 | users/discord_123456789012345678.md |
| line | Uabc1234567890 | 小花 | users/line_Uabc1234567890.md |
```

## 個人記憶檔格式

```markdown
# {稱呼}

- **頻道**：discord / line
- **User ID**：{user_id}
- **最後互動**：{YYYY-MM-DD}

## 基本資訊

- 角色/身份：
- 偏好：
- 備註：

## 互動記錄

- {YYYY-MM-DD}：{重要事項}
```

## 執行步驟（每次 compact 時）

**Step 1：找出這次對話的所有 sender**

- Discord 頻道／DM：從訊息 metadata 取得 author.id
- LINE：從 source.userId 取得
- Group chat：可能有多人，全部逐一處理

**Step 2：對每位 sender 比對目錄**

1. 開啟 `memory/MEMORY.md`，找 `## 成員目錄` 表格
2. 用 `channel + user_id` 比對每一行
3. **找到** → 讀取對應的 `users/{file}.md`
4. **找不到** → 在 `memory/users/` 建立新檔，檔名格式 `{channel}_{user_id}.md`，並在 MEMORY.md 目錄新增一行

**Step 3：更新個人檔**

根據這次對話內容更新：
- 有提到名字或自我介紹 → 更新稱呼與基本資訊
- 有表達偏好、習慣或立場 → 寫入「偏好」欄
- 有重要決定、任務或事件 → 加入「互動記錄」並附上日期
- 無論如何都要更新「最後互動」日期

**Step 4：儲存**

寫回 `memory/users/{file}.md` 與 `memory/MEMORY.md`

## 規則

- 只記錄**有意義**的資訊，不要流水帳
- 不記錄敏感個人資料（電話、住址、財務）
- Group chat 同一次 compact 可能要更新多個人
- 對話很短且無新資訊時，只更新「最後互動」日期即可
- 稱呼未知時，暫用 `user_{id末4碼}` 作為預設稱呼，等對方自我介紹再更新
