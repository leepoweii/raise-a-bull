---
name: generate-image
description: 圖片生成工具。用 Screenshot Service 產生宣傳圖、活動海報、社群貼文、資訊圖等靜態圖片。使用時機：做圖、設計、海報、社群貼文、活動宣傳、資訊圖表。
---

# generate-image — 培力站圖片生成

用 agents-infra Screenshot Service 將 HTML/CSS 轉為靜態圖片。

## Screenshot Service（agents-infra）

- URL: `$AGENTS_INFRA_URL` → `http://agents-gateway:8000`
- Header: `x-api-key: $AGENTS_INFRA_API_KEY`

### POST /screenshot

```json
{
  "html": "<完整 HTML 文件>",
  "width": 1080,
  "height": 1080,
  "format": "png",
  "selector": null
}
```

Response: 圖片 binary

### exec curl

先用 write tool 將 HTML 寫入 `/tmp/output.html`，再執行：

```bash
jq -n --rawfile html /tmp/output.html \
  '{html: $html, width: 1080, height: 1080, format: "png"}' \
  > /tmp/screenshot_payload.json

curl -s -X POST "$AGENTS_INFRA_URL/screenshot" \
  -H 'Content-Type: application/json' \
  -H "x-api-key: $AGENTS_INFRA_API_KEY" \
  -d @/tmp/screenshot_payload.json \
  --output /tmp/output.png
```

## 品牌規範 — 寂寞寂寞山芭地培力站

### 品牌色（來自 site-v2 設計系統）

| 名稱 | 色碼 | CSS 變數 | 用途 |
|------|------|----------|------|
| 氧化酒紅 | `#541E17` | `--color-primary` | 主色，品牌色 |
| 琥珀金 | `#C9821A` | `--color-accent` | 強調色，CTA、裝飾 |
| 暖米 | `#F3EFE9` | `--color-bg` | 底色，背景 |
| 深墨 | `#2D2D2D` | `--color-text` | 內文文字 |
| 墨黑 | `#1C1208` | `--color-ink` | 標題、深色文字 |
| 邊線灰 | `#D5C9BE` | `--color-border` | 分隔線、邊框 |
| 林綠 | `#4A7C59` | `--color-success` | 成功、自然 |
| 霧藍 | `#8B9EB7` | `--color-event` | 活動資訊 |
| 需求橘 | `#C4813A` | `--color-listing-need` | 需求標籤 |
| 資源綠 | `#6A9E72` | `--color-listing-resource` | 資源標籤 |

### 設計風格

報紙美學（Newspaper aesthetic）——銳利邊角，無圓角（border-radius: 0），復古印刷感。

### 字體

```html
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&family=Noto+Serif+TC:wght@400;600;700&display=swap" rel="stylesheet">
```

- 標題：`Noto Serif TC`（有文化感）
- 內文：`Noto Sans TC`（清爽好讀）

### 最小字級

- 中文：`28px`
- 英文：`24px`
- 輔助文字/label：`20px`

### Logo（暫時用文字）

```html
<div style="font-family:'Noto Serif TC',serif;font-weight:700;font-size:36px;color:#541E17;letter-spacing:4px;">
  寂寞寂寞山芭地
</div>
<div style="font-family:'Noto Sans TC',sans-serif;font-size:16px;color:#2D2D2D;letter-spacing:6px;margin-top:4px;">
  金門青年培力站
</div>
```

## 用途與尺寸

| 用途 | width | height |
|---|---:|---:|
| IG 貼文 | 1080 | 1080 |
| IG Story | 1080 | 1920 |
| FB 貼文 | 1200 | 630 |
| 活動海報 | 1080 | 1520 |
| 資訊圖（橫） | 1920 | 1080 |

## 設計風格指引

### 培力站適合的風格

- **溫暖、在地、務實**——不是觀光局，不是科技感，是金門鄰居的感覺
- 報紙美學：銳利邊角、印刷感排版、大膽字級對比
- 用暖色調為主（酒紅、琥珀金、暖米）
- 照片風格偏日常、紀實，不要修太光滑
- 可以適度使用閩南建築紋樣作裝飾
- 留白多一點，不要擠得太滿

### 排版原則

1. **混合對齊**——不要全置中，標題左對齊、資訊用 grid
2. **字級對比**——大標至少 `72px`，小字 `24px`，比例 3:1 以上
3. **呼吸空間**——padding 至少 `60px`
4. **樸實感**——不需要太多特效，乾淨就好
5. **無圓角**——所有 border-radius 設為 0
6. 可以用底部色塊放站名和日期

### CSS 效果（適度使用）

紙張質感疊層：
```html
<div style="position:absolute;inset:0;opacity:0.05;pointer-events:none;background-image:url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 600 600%22%3E%3Cfilter id=%22a%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%22.65%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23a)%22/%3E%3C/svg%3E');background-repeat:repeat;background-size:200px"></div>
```

色塊分隔線：
```html
<div style="width:60px;height:4px;background:#541E17;margin:16px 0;"></div>
```

金色裝飾線：
```html
<div style="width:80px;height:2px;background:#C9821A;margin:12px 0;"></div>
```

## 內容類型建議

| 類型 | 配色 |
|------|------|
| 活動宣傳 | 暖米底 + 酒紅強調 + 琥珀金裝飾 |
| 青年故事 | 暖米底 + 霧藍點綴 |
| 課程資訊 | 墨黑底 + 暖米文字 + 琥珀金強調 |
| 自然生態 | 林綠底 + 暖米文字 |
| 一般公告 | 暖米底 + 深墨文字 + 酒紅裝飾線 |

## 發送圖片（重要）

產生圖片後，**不要用 message tool 發送圖片**（會 400 錯誤）。

### Discord 發送

在回覆文字中**另起一行**寫 `MEDIA:` 加上檔案路徑，OpenClaw 會自動附加圖片：

```
報告！行事曆畫好了，請過目～
MEDIA:/tmp/output.png
```

### LINE 發送

LINE 不支援本地檔案，必須透過公開 URL。使用 agents-infra CDN 上傳：

1. 產生圖片到 `/tmp/output.png`
2. 上傳到 CDN：

```bash
CDN_RESPONSE=$(curl -sf -X POST "$AGENTS_INFRA_URL/upload/peili" \
  -H "x-api-key: $AGENTS_INFRA_API_KEY" \
  -F "file=@/tmp/output.png;filename=output.png")
CDN_URL=$(echo "$CDN_RESPONSE" | jq -r '.url')
```

3. 用公開 URL 回覆：`MEDIA:$CDN_URL`

### 完整流程

1. 用 `exec` + `curl` 呼叫 `$AGENTS_INFRA_URL/screenshot`，`--output /tmp/output.png`
2. 如果是 LINE 頻道，上傳到 `$AGENTS_INFRA_URL/upload/peili` 取得 CDN URL
3. Discord: 回覆最後加 `MEDIA:/tmp/output.png`
4. LINE: 回覆最後加 `MEDIA:$CDN_URL`

### agents-infra 端點

- Screenshot: `$AGENTS_INFRA_URL/screenshot`（Header: `x-api-key: $AGENTS_INFRA_API_KEY`）
- Upload/CDN: `$AGENTS_INFRA_URL/upload/peili`（POST multipart, Header: `x-api-key: $AGENTS_INFRA_API_KEY`）
- CDN URL base: `$CDN_BASE_URL`（`https://cdn.pwlee.xyz`）

## 實作規則

1. 生成完整 HTML 文件（含 `<!DOCTYPE html>`）
2. `<head>` 內加入 Google Fonts link
3. 遵守品牌色與字體規範
4. 所有元素 `border-radius: 0`（報紙美學）
5. 用 Screenshot Service 產生圖片
6. 用 `curl --output /tmp/output.png` 存檔
7. 在回覆文字最後加 `MEDIA:/tmp/output.png` 發送圖片（Discord）
8. LINE 頻道需上傳 CDN 後用 `MEDIA:$CDN_URL`

## 禁止

1. 禁止使用觀光局口吻（「必去景點！」「CP 值超高！」）
2. 禁止科技感 UI 風格（漸層按鈕、霓虹色）
3. 禁止字級低於最小值
4. 禁止全部置中排版
5. 禁止使用圓角（border-radius > 0）
6. 禁止直接 cp 到 public/images（改用 upload API）
