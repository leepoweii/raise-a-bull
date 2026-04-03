---
name: ig-story-design
description: 生成 IG Story 或 IG Post 設計圖。觸發詞：做限動、IG Story、IG Post、宣傳圖、海報、活動限動、design、做圖、設計一個、做一張、幫我做、行事曆。收到設計需求後選模板、讀品牌、填內容、截圖、上傳、發送。
---

# IG Story / Post Design Studio

## 執行流程（照順序，不可跳步）

1. **讀品牌** — `read brand/identity.md` if it exists, otherwise use params.json brand settings（顏色、字體、logo、風格規則）
2. **選模板** — 根據下方選擇表選一個模板
3. **讀模板** — `read skills/ig-story-design/templates/<模板>.html`
4. **填內容** — 替換所有 `{{PLACEHOLDER}}`（對照表見 `templates/TEMPLATE-GUIDE.md`）
5. **截圖** — Screenshot Service → `/tmp/story.jpg`
6. **上傳 CDN** — 取得公開 URL
7. **發送** — 依照下方發送格式

### 禁止

- ❌ 不讀模板就自己從零寫 HTML（除非用戶明確說「全新設計」）
- ❌ 收到簡單提示時先問「你要什麼內容？」— 用合理預設值先做，之後讓對方改
- ❌ 違反品牌規則（圓角、霓虹色、全置中等）

---

## 模板選擇

| 用戶說 | 模板 |
|--------|------|
| 活動、講座、市集、表演 | `event-announcement.html` |
| 課程、工作坊、培力課 | `workshop-info.html` |
| 公告、休站、通知 | `notice-general.html` |
| 照片 + 故事、人物、活動紀實 | `photo-story.html` |
| 本週行程 | `calendar-weekly.html` |
| 月行事曆、當月營業日曆 | `calendar-monthly-april.html`（以 April 版為基底，更新月份和日期） |

Placeholder 完整對照 → `templates/TEMPLATE-GUIDE.md`

---

## API

### 步驟一：寫 HTML 到暫存檔

用 write tool 將完整 HTML 寫到 `/tmp/ig_story.html`。

### 步驟二：截圖

```bash
jq -n --rawfile html /tmp/ig_story.html \
  '{html: $html, width: 1080, height: 1920, format: "jpeg", quality: 90}' \
  > /tmp/screenshot_payload.json

curl -s -X POST "$AGENTS_INFRA_URL/screenshot" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $AGENTS_INFRA_API_KEY" \
  -d @/tmp/screenshot_payload.json \
  --output /tmp/story.jpg
```

IG Post（正方形）：改 `height: 1080`

### 步驟三：上傳 CDN

```bash
CDN_URL=$(curl -sf -X POST "$AGENTS_INFRA_URL/upload/{instance_id}" \
  -H "x-api-key: $AGENTS_INFRA_API_KEY" \
  -F "file=@/tmp/story.jpg;filename=ig-$(date +%Y%m%d%H%M%S).jpg" \
  | jq -r '.url')
```

### 步驟四：發送

**LINE（用 CDN URL 發圖片）：**
```
MEDIA:$CDN_URL
```

**Discord（貼 CDN URL，自動展開圖片）：**
```
$CDN_URL
```

---

## 從零設計（無適合模板時）

1. 讀 `brand/identity.md` 取得所有品牌規則
2. 讀 `templates/frames/brand-frame.html` 作為基礎框架
3. 設計規則詳見 `templates/TEMPLATE-GUIDE.md`
