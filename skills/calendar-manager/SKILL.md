---
name: calendar-manager
description: 行事曆管理。查看行程、新增活動、排會議、提醒即將到來的事件。使用 gog calendar CLI。
---

# calendar-manager

管理 Google Calendar 行事曆：查看行程、新增活動、檢查空閒時段、找衝突。

## 設定

讀取 `../../params.json` 的以下欄位：

| 欄位 | 說明 | 預設值 |
|---|---|---|
| `calendar.account` | Google 帳號 email | （必填，無預設） |
| `calendar.default_calendar` | 預設行事曆 ID | `primary` |
| `calendar.timezone` | 時區 | `Asia/Taipei` |

所有 `gog calendar` 指令都要加 `-a {account}` 指定帳號。

## 工具

使用 `gog calendar` CLI（透過 exec/bash），**不要用 web_fetch**。

gog 路徑：`/home/linuxbrew/.linuxbrew/bin/gog`

## 常用操作

### 查看行程

```bash
# 今天的行程
gog calendar events -a {account} --today

# 明天的行程
gog calendar events -a {account} --tomorrow

# 指定日期範圍
gog calendar events -a {account} --from 2026-03-15 --to 2026-03-16

# 本週行程
gog calendar events -a {account} --week

# 未來 N 天
gog calendar events -a {account} --days 3

# 指定行事曆
gog calendar events -a {account} --cal "工作" --today

# 所有行事曆
gog calendar events -a {account} --all --today

# JSON 格式（方便解析）
gog calendar events -a {account} --today -j --results-only
```

### 搜尋活動

```bash
# 關鍵字搜尋
gog calendar search "會議" -a {account} --days 7

# 搜尋特定日期範圍
gog calendar search "報告" -a {account} --from 2026-03-10 --to 2026-03-20
```

### 新增活動

```bash
# 基本活動
gog calendar create primary -a {account} \
  --summary "團隊會議" \
  --from "2026-03-15T14:00:00+08:00" \
  --to "2026-03-15T15:00:00+08:00"

# 含地點與說明
gog calendar create primary -a {account} \
  --summary "客戶拜訪" \
  --from "2026-03-15T10:00:00+08:00" \
  --to "2026-03-15T11:30:00+08:00" \
  --location "台北市信義區" \
  --description "Q2 合作討論"

# 全天活動
gog calendar create primary -a {account} \
  --summary "員工旅遊" \
  --from "2026-03-20" \
  --to "2026-03-21" \
  --all-day

# 含 Google Meet
gog calendar create primary -a {account} \
  --summary "線上週會" \
  --from "2026-03-15T09:00:00+08:00" \
  --to "2026-03-15T09:30:00+08:00" \
  --with-meet

# 含提醒（提前 30 分鐘）
gog calendar create primary -a {account} \
  --summary "面試" \
  --from "2026-03-15T14:00:00+08:00" \
  --to "2026-03-15T15:00:00+08:00" \
  --reminder popup:30m

# 含邀請對象
gog calendar create primary -a {account} \
  --summary "專案 kickoff" \
  --from "2026-03-15T10:00:00+08:00" \
  --to "2026-03-15T11:00:00+08:00" \
  --attendees "alice@example.com,bob@example.com" \
  --send-updates all

# 週期性活動
gog calendar create primary -a {account} \
  --summary "每週站會" \
  --from "2026-03-17T09:00:00+08:00" \
  --to "2026-03-17T09:15:00+08:00" \
  --rrule "RRULE:FREQ=WEEKLY;BYDAY=MO"
```

### 檢查空閒時段

```bash
# 查詢某段時間是否有空
gog calendar freebusy -a {account} \
  --from "2026-03-15T09:00:00+08:00" \
  --to "2026-03-15T18:00:00+08:00"
```

### 檢查衝突

```bash
# 今天的行程衝突
gog calendar conflicts -a {account} --today

# 本週衝突
gog calendar conflicts -a {account} --week

# 所有行事曆的衝突
gog calendar conflicts -a {account} --week --all
```

### 更新 / 刪除活動

```bash
# 更新活動（需要 calendarId 和 eventId）
gog calendar update primary {eventId} -a {account} --summary "新標題"

# 刪除活動
gog calendar delete primary {eventId} -a {account} -y
```

### 列出行事曆

```bash
# 看有哪些行事曆
gog calendar calendars -a {account}
```

## 使用情境與回覆範例

### 「今天有什麼行程？」

1. 執行 `gog calendar events -a {account} --today --all -j --results-only`
2. 按時間排序，分上午/下午/晚上整理
3. 回覆範例：

```
📅 今天（3/15 週六）的行程：

【上午】
• 09:00-09:30 — 每週站會
• 10:00-11:30 — 客戶拜訪（台北市信義區）

【下午】
• 14:00-15:00 — 團隊會議

晚上沒有行程，可以好好休息。
```

### 「明天下午有空嗎？」

1. 執行 `gog calendar freebusy -a {account} --from "明天T13:00:00+08:00" --to "明天T18:00:00+08:00"`
2. 也執行 `gog calendar events -a {account} --tomorrow -j --results-only` 看具體行程
3. 回覆範例：

```
明天下午 13:00-15:00 有「專案討論」，15:00 之後到 18:00 都是空的。
```

### 「幫我排一個會議」

1. 先確認：時間、標題、地點、參與者
2. 如果資訊不完整，主動詢問
3. 新增前用 `--dry-run` 確認，再正式建立
4. 回覆範例：

```
已建立：
📌 專案 kickoff
🕐 3/17（一）10:00-11:00
📍 會議室 A
👥 已邀請 alice@example.com、bob@example.com
🔗 Google Meet 連結已自動產生
```

### 「這週有沒有行程衝突？」

1. 執行 `gog calendar conflicts -a {account} --week --all`
2. 若有衝突，列出衝突的活動與時段
3. 回覆範例：

```
⚠️ 本週有 1 個衝突：

週三 3/19 14:00-15:00：
  • 「團隊會議」（工作）
  • 「客戶電話」（個人）

建議把其中一個調整時間。
```

## 回覆原則

1. **繁體中文**回覆
2. 時間用 **24 小時制**（如 14:00，不要寫下午 2 點）
3. 行程按時段分組：**上午**（06:00-12:00）、**下午**（12:00-18:00）、**晚上**（18:00-24:00）
4. 全天活動放最前面，標註「全天」
5. 有衝突時主動提醒並建議調整
6. 新增活動前若缺少關鍵資訊（時間、標題），主動詢問，不要猜
7. 新增活動時優先加 `--dry-run` 讓使用者確認，確認後再正式建立
8. 不要把 JSON 原始資料丟給使用者，整理成易讀格式
9. 日期加上星期幾，方便使用者判斷

## 時間格式

gog 支援的時間格式：
- RFC3339：`2026-03-15T14:00:00+08:00`
- 日期：`2026-03-15`
- 相對時間：`today`、`tomorrow`、`monday`（下一個週一）

建立活動時，時間必須用 RFC3339 含時區（`+08:00`）。

## 錯誤處理

- 帳號未設定 → 「請在 params.json 設定 calendar.account」
- 認證失敗 → 「Google 帳號認證有問題，請聯絡管理員」
- 找不到活動 → 「這段時間沒有行程」
- 指令執行失敗 → 顯示錯誤訊息，建議可能的修正方式

## 重要規則

1. 一定要從 `../../params.json` 讀取 `calendar.account`，每個 gog 指令都要帶 `-a {account}`
2. 用 exec/bash 執行 gog，不要用 web_fetch
3. 新增或修改活動前先用 `--dry-run` 確認
4. 刪除活動前先跟使用者確認
5. 不要暴露 eventId 等技術細節給使用者
6. 查詢多個行事曆時用 `--all` 確保不遺漏
