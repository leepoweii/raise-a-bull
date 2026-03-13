---
name: inbox-triage
description: Email 摘要分類。掃描未讀信件、分類優先級、摘要重要內容。使用 gog gmail CLI。
---

# Inbox Triage

> **Phase 1 — Read-only STUB**
> 目前僅支援掃描與摘要，不支援回覆、轉寄、封存（未來擴充）。

---

## Tool

使用 `gog gmail` CLI（Gmail API wrapper）。

### 常用指令

```bash
# 掃描未讀信件（預設最多 10 封）
gog gmail search "is:unread in:inbox" --max 10

# 依寄件人搜尋
gog gmail search "from:xxx@email.com" --max 5

# 依主旨關鍵字搜尋
gog gmail search "subject:關鍵字" --max 5
```

如有 `params.json`，從中讀取 Gmail 帳號設定。

---

## Triage 流程

1. 執行 `gog gmail search "is:unread in:inbox" --max 10` 取得未讀信件
2. 逐封判讀寄件人、主旨、時間
3. 分類為以下四級：
   - **🔴 緊急** — 今天需要回覆（老闆、客戶、截止日迫近）
   - **🟡 重要** — 本週內需處理（合作夥伴、專案相關）
   - **🟢 參考** — 僅供閱讀，不需行動（通知、FYI）
   - **⚪ 可忽略** — 電子報、促銷、自動通知
4. 輸出摘要報告

---

## 輸出格式

```
📬 未讀信件摘要（共 X 封）

🔴 緊急（Y 封）
- [寄件人] 主旨 — 一句話摘要

🟡 重要（Z 封）
- [寄件人] 主旨 — 一句話摘要

🟢 參考（Z 封）
- [寄件人] 主旨 — 一句話摘要

⚪ 可忽略（Z 封）
- [寄件人] 主旨
```

---

## 規則

- 一律使用繁體中文
- 預設不顯示完整信件內容，除非使用者要求
- 摘要中不暴露敏感資訊（密碼、驗證碼、個資）
- 若 `params.json` 存在，從中讀取 Gmail 帳號設定
