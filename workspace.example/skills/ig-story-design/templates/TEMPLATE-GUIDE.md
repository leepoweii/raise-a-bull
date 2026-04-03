# 培力站 IG Story 模板指南

## 模板清單

| 模板 | 用途 | 排版模式 | 底色 |
|------|------|---------|------|
| `event-announcement.html` | 活動宣傳、講座、市集 | Editorial Stack | 暖米 `#F3EFE9` |
| `notice-general.html` | 一般公告、營業時間、休站通知 | Split Block | 暖米 `#F3EFE9` |
| `workshop-info.html` | 課程、工作坊、培力課程 | Asymmetric Column | 墨黑 `#1C1208` |
| `photo-story.html` | 照片故事、人物專訪、活動紀實 | Photo Hero | 照片 + overlay |
| `calendar-weekly.html` | 每週行程表、活動日曆 | Day Row List | 暖米 `#F3EFE9` |

## 使用流程

1. 根據內容類型選擇模板
2. 用 `read` 讀取模板 HTML
3. 替換以下佔位符：
   - `{{TITLE}}` — 主標題
   - `{{SUBTITLE}}` — 副標題（可選）
   - `{{DATE}}` — 日期
   - `{{TIME}}` — 時間（可選）
   - `{{LOCATION}}` — 地點（可選）
   - `{{DESCRIPTION}}` — 說明文字
   - `{{TAG}}` — 標籤文字（如「活動」「公告」）
   - `{{PHOTO_URL}}` — 照片 URL（photo-story 用）
4. 送進 Screenshot Service（1080×1920）

### `calendar-weekly.html` 專用佔位符

| 佔位符 | 說明 | 範例 |
|--------|------|------|
| `{{WEEK_RANGE}}` | 週次日期範圍 | `3/17 — 3/23` |
| `{{DAY_1_DATE}}` ~ `{{DAY_7_DATE}}` | 每日日期（一～日） | `3/17` |
| `{{DAY_1_EVENTS}}` ~ `{{DAY_7_EVENTS}}` | 每日事項（支援 HTML） | 見下方色碼 |

#### 事件色碼 HTML 格式

活動（琥珀金）：
```html
<span style="color:#C9821A;font-weight:500;">● </span>社區營造講座 14:00
```

會議（霧藍）：
```html
<span style="color:#8B9EB7;font-weight:500;">● </span>團隊週會 10:00
```

已完成（林綠）：
```html
<span style="color:#4A7C59;font-weight:500;">● </span><span style="text-decoration:line-through;opacity:0.6;">物資盤點</span>
```

多個事件用 `<br>` 換行。無事項時留空或填 `<span style="color:#D5C9BE;">— 無行程 —</span>`。

## 品牌色速查

| 色碼 | 名稱 | 用途 |
|------|------|------|
| `#541E17` | 氧化酒紅 | 主色 |
| `#C9821A` | 琥珀金 | 強調、活動標記 |
| `#F3EFE9` | 暖米 | 底色 |
| `#2D2D2D` | 深墨 | 內文 |
| `#1C1208` | 墨黑 | 標題 |
| `#D5C9BE` | 邊線灰 | 邊框 |
| `#4A7C59` | 林綠 | 已完成標記 |
| `#8B9EB7` | 霧藍 | 會議標記 |

## 注意事項

- 所有元素 `border-radius: 0`（報紙美學）
- 每張設計必須加紙張質感疊層
- IG 安全區域：頂部 250px、底部 250px 不放重要內容
- 左右邊距至少 65px
