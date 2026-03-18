# raise-a-bull

> **raise-a-bull** — 金門地方組織的 AI 辦公室助理飼料包
>
> *Feed pack for deploying OpenClaw AI office assistants to Kinmen local organizations*

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/leepoweii/raise-a-bull.git
cd raise-a-bull

# 2. Raise — 用 preset 生成一頭牛
./scripts/raise.sh --preset bar --name 小茉

# 3. Fill secrets & start
cp secrets/.env.example secrets/.env
# 填入 API keys，然後開始使用
```

---

## Repo Structure

```
raise-a-bull/
├── VERSION                  # 語意版號
├── schemas/                 # 規格定義（bull / params / managed-state）
├── identity/                # 身份設定
│   ├── regions/kinmen/      # 金門在地化資料
│   └── templates/           # 身份模板
├── skills/                  # 技能模組（每個技能一個資料夾）
│   ├── daily-review/
│   ├── calendar-manager/
│   ├── inbox-triage/
│   ├── follow-up-tracker/
│   ├── meeting-notes/
│   ├── document-draft/
│   ├── knowledge-base/
│   ├── image-generation/
│   ├── weather-cwa/
│   └── identity-update/
├── presets/                 # 預設組合包（bar, association, shop, office）
├── scripts/                 # CLI 工具
├── templates/               # 通用模板
└── docs/                    # 文件
```

---

## Skills

| Skill | 說明 | 狀態 |
|---|---|---|
| `daily-review` | 每日復盤與排程 | stub |
| `calendar-manager` | Google Calendar 管理 | stub |
| `inbox-triage` | 訊息分類與回覆建議 | stub |
| `follow-up-tracker` | 追蹤待辦與提醒 | stub |
| `meeting-notes` | 會議記錄整理 | stub |
| `document-draft` | 公文 / 企劃書草稿 | stub |
| `knowledge-base` | 在地知識庫查詢 | stub |
| `image-generation` | 社群圖片生成 | stub |
| `weather-cwa` | 中央氣象署天氣查詢 | stub |
| `identity-update` | 身份設定熱更新 | stub |

---

## Presets

| Preset | 說明 | 適用場景 |
|---|---|---|
| `bar` | 酒吧助理 | 夢酒館、小型餐飲 |
| `association` | 協會助理 | 社區發展協會、地方團體 |
| `shop` | 店家助理 | 零售、伴手禮店 |
| `office` | 辦公室助理 | 工作站、一般辦公室 |

---

## Scripts

| Script | 用途 |
|---|---|
| `raise.sh` | 從 preset 生成新的 bull instance |
| `feed.sh` | 更新技能或身份設定 |
| `doctor.sh` | 健康檢查（設定驗證） |
| `sanitize.sh` | 清除敏感資料 |
| `backup.sh` | 備份 bull 設定與狀態 |

---

## License

MIT
