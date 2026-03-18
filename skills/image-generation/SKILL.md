---
name: image-generation
description: 圖片生成工具。用 HTML/CSS 產生圖片。使用時機：做圖、設計、海報、IG 貼文、限動、social media 圖片、宣傳圖。
---

# generate-image

用 HTML/CSS 設計圖片，透過 htmlcsstoimage API 輸出。

## API

環境變數：`HCTI_USER_ID`、`HCTI_API_KEY`

```bash
exec curl -u "$HCTI_USER_ID:$HCTI_API_KEY" \
  -d html="<HTML>" -d css="" \
  -d google_fonts="Cormorant Garamond|600,Noto Sans TC|400,DM Sans|400" \
  -d viewport_width=1080 -d viewport_height=1080 \
  https://hcti.io/v1/image
```

- `google_fonts`：依品牌設定調整，格式為 `FontName|weight`，多組用逗號分隔
- `viewport_width` / `viewport_height`：依用途調整（見尺寸參考）

## 品牌設定

讀取 `../../params.json` 的 `brand.*`（primary_color, accent_color, font_cn, font_en）。

- Logo 必須用 `<img>` 標籤，圖片路徑從 `brand.logo_url` 取得
- **禁止用文字取代 Logo 圖片**
- 色彩、字體一律從 params.json 讀取，不要硬編碼

## 字體規則

- 英文主標：使用 `brand.font_en`（如 Cormorant Garamond）
- 中文內文：使用 `brand.font_cn`（如 Noto Sans TC）
- **google_fonts 必帶中文字體，否則中文會亂碼**
- 所有中文內容都需要對應的 Google Fonts 中文字體支援

## 尺寸參考

| 用途 | width | height |
|------|-------|--------|
| IG 貼文（方形） | 1080 | 1080 |
| IG 限動 | 1080 | 1920 |
| 菜單卡 / 傳單 | 800 | 1200 |
| 橫幅 Banner | 1200 | 628 |

## HTML/CSS 設計原則

1. 所有樣式寫在 HTML 的 inline style 或 `<style>` 標籤內（css 參數留空）
2. 用 flexbox 排版，避免絕對定位
3. 確保文字在背景色上有足夠對比度
4. 圖片素材用完整 URL（https://）

## 用量限制

htmlcsstoimage 免費版 **50 張/月**，注意用量。

- 開發測試時先用小尺寸預覽
- 確認設計後再輸出正式尺寸
- 避免迴圈或批次大量呼叫
