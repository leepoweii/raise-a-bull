---
name: generate-image
description: 圖片生成工具。用 Screenshot Service 產生宣傳圖、活動海報、社群貼文、資訊圖等靜態圖片。使用時機：做圖、設計、海報、社群貼文、活動宣傳、資訊圖表。
---

# generate-image — 圖片生成

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

## 品牌規範

讀取 params.json 中的 brand 設定（名稱、字體、顏色）。如果 brand/ 目錄有 identity.md，也一併讀取。

## 用途與尺寸

| 用途 | width | height |
|---|---:|---:|
| IG 貼文 | 1080 | 1080 |
| IG Story | 1080 | 1920 |
| FB 貼文 | 1200 | 630 |
| 活動海報 | 1080 | 1520 |
| 資訊圖（橫） | 1920 | 1080 |

## 設計風格指引

### 風格建議

- 參照 brand/ identity 與 params.json 的品牌設定
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

在回覆文字中**另起一行**寫 `MEDIA:` 加上檔案路徑，raise-a-bull 會自動附加圖片：

```
報告！行事曆畫好了，請過目～
MEDIA:/tmp/output.png
```

### LINE 發送

LINE 不支援本地檔案，必須透過公開 URL。使用 agents-infra CDN 上傳：

1. 產生圖片到 `/tmp/output.png`
2. 上傳到 CDN：

```bash
CDN_RESPONSE=$(curl -sf -X POST "$AGENTS_INFRA_URL/upload/{instance_id}" \
  -H "x-api-key: $AGENTS_INFRA_API_KEY" \
  -F "file=@/tmp/output.png;filename=output.png")
CDN_URL=$(echo "$CDN_RESPONSE" | jq -r '.url')
```

3. 用公開 URL 回覆：`MEDIA:$CDN_URL`

### 完整流程

1. 用 `exec` + `curl` 呼叫 `$AGENTS_INFRA_URL/screenshot`，`--output /tmp/output.png`
2. 如果是 LINE 頻道，上傳到 `$AGENTS_INFRA_URL/upload/{instance_id}` 取得 CDN URL（instance_id 來自 bull.json）
3. Discord: 回覆最後加 `MEDIA:/tmp/output.png`
4. LINE: 回覆最後加 `MEDIA:$CDN_URL`

### agents-infra 端點

- Screenshot: `$AGENTS_INFRA_URL/screenshot`（Header: `x-api-key: $AGENTS_INFRA_API_KEY`）
- Upload/CDN: `$AGENTS_INFRA_URL/upload/{instance_id}`（POST multipart, Header: `x-api-key: $AGENTS_INFRA_API_KEY`，instance_id 來自 bull.json）
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
