---
name: daily-review
description: 每日回顧。早上建立今日焦點，晚上回顧完成度與能量。使用 gog tasks/calendar CLI。
---

> **STUB**: 這是核心版。完整版（含 heartbeat、週回顧、情緒 check-in）
> 待 Samantha 定義 spec 後實作。

# Daily Review — Core Loop

## 工具

- Google Tasks: `gog tasks`
- Google Calendar: `gog calendar`

## 設定

- Task list ID: 從 `params.json` 讀取 `tasks.focus_list_id`

## Tasks Notes 格式

```
⚡___  🔋___  💬___
```

- ⚡ = friction（1-5，啟動阻力）
- 🔋 = energy（-3 到 +3，消耗或充電）
- 💬 = comment（一句話感想）

---

## ☀️ Morning — 建立今日焦點

### 觸發

使用者說「早安」「今日焦點」或類似意圖。

### 流程（5 步）

1. **讀取今日行程**
   ```bash
   gog calendar events <calendar_id> --today
   ```

2. **讀取待辦清單**
   ```bash
   gog tasks list <todo_list_id>
   ```

3. **檢查昨日殘留**
   ```bash
   gog tasks list <focus_list_id>
   ```
   如果有殘留 → 問使用者：繼續做 / 放掉？

4. **提議今日焦點（3-5 項）**
   組合行程 + 待辦中最重要的幾件事。
   一次提出，等使用者確認或調整。

5. **寫入 focus list**
   ```bash
   gog tasks add <focus_list_id> \
     --title "任務名稱" --notes "⚡___  🔋___  💬___"
   ```

### 訊息範例

```
☀️ 早安！今天是 MM/DD（星期X）

📅 行程：
- 14:00 某某會議

📋 建議今日焦點：
1. 某某會議 14:00
2. 最重要的事
3. 第二重要的事

OK 嗎？要調整什麼？
```

---

## 🌙 Evening — 回顧今天

### 觸發

使用者說「回顧」「review」或類似意圖。

### 流程（5 步）

1. **讀取 focus list**
   ```bash
   gog tasks list <focus_list_id> --show-completed --show-hidden
   ```

2. **逐項走過**（一項一項來，不要一次問全部）
   - 已完成 → 補填 ⚡🔋💬
   - 未完成 → 問：繼續做 / 拆更小 / 放掉？

3. **更新 task notes**
   ```bash
   gog tasks update <focus_list_id> <task_id> \
     --notes "⚡2  🔋-1  💬累但有學到"
   ```

4. **處理未完成**
   - 繼續做 → 移回待辦清單
   - 拆更小 → 新任務加入待辦
   - 放掉 → 刪除

5. **能量總結 + 清空 focus list**
   完成 X/Y 項，總能量 +/-N。
   刪除 focus list 中所有 tasks。

### 訊息範例

```
🌙 來回顧今天吧！

✅ 某某會議 — 怎麼樣？
（等回覆 → 記 ⚡🔋💬）

⬜ 寫報告 — 沒做到？
→ 繼續做 / 拆更小 / 放掉？

---
📊 今日：完成 2/3，總能量 +1
```

---

## 核心原則

- 這是**陪伴**，不是績效考核
- 沒完成就是沒完成，不需要解釋
- ADHD 友善：簡單、不批判、guilt-free
- 一項一項走，不要一次問全部
