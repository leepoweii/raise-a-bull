# Accounts & Services Checklist

> AI agent 可讀的帳號/服務清單。每個項目列出：服務名稱、註冊網址、需要取得的資料、對應的環境變數、存放位置。

---

## Required（必填）

### OpenAI API

| 項目 | 內容 |
|---|---|
| **服務** | OpenAI API |
| **網址** | https://console.openai.com → API Keys |
| **取得** | API Key（以 `sk-` 開頭） |
| **環境變數** | `OPENAI_API_KEY` |
| **存放位置** | `workspace/secrets/provider.env` |

### Google Workspace（Calendar / Tasks / Gmail）

| 項目 | 內容 |
|---|---|
| **服務** | Google Workspace（Calendar, Tasks, Gmail） |
| **網址** | Google Cloud Console → OAuth 或 Service Account |
| **取得** | OAuth credentials 或 service account JSON |
| **環境變數** | `GOOGLE_CREDENTIALS`（或放 JSON 檔案） |
| **存放位置** | `workspace/secrets/google_credentials.json` |
| **備註** | 需要 gog CLI 授權；association / office preset 必須 |

---

## Channel-Specific（依頻道選用）

### LINE Messaging API

| 項目 | 內容 |
|---|---|
| **服務** | LINE Messaging API |
| **網址** | https://developers.line.biz → 建立 Channel |
| **取得** | Channel Secret + Channel Access Token |
| **環境變數** | `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` |
| **存放位置** | `workspace/secrets/provider.env` |
| **備註** | preset 的 `channels` 包含 `"line"` 時必填 |

### Discord Bot

| 項目 | 內容 |
|---|---|
| **服務** | Discord Bot |
| **網址** | https://discord.com/developers → Applications → Bot |
| **取得** | Bot Token |
| **環境變數** | `DISCORD_BOT_TOKEN` |
| **存放位置** | `workspace/secrets/provider.env` |
| **備註** | preset 的 `channels` 包含 `"discord"` 時必填 |

---

## Optional（選填）

### CWA 中央氣象署

| 項目 | 內容 |
|---|---|
| **服務** | 中央氣象署 開放資料平台 |
| **網址** | https://opendata.cwa.gov.tw → 會員申請 → 取得 Authorization Key |
| **取得** | Authorization Key（以 `CWA-` 開頭） |
| **環境變數** | `CWA_API_KEY` |
| **存放位置** | `workspace/secrets/provider.env` 或 `workspace/secrets/cwa_api_key` |
| **備註** | `weather-cwa` skill 需要；preset integrations 有 `cwa: true` 時建議填寫 |

### htmlcsstoimage

| 項目 | 內容 |
|---|---|
| **服務** | htmlcsstoimage（HTML 轉圖片） |
| **網址** | https://hcti.io → 註冊帳號 |
| **取得** | User ID + API Key |
| **環境變數** | `HCTI_USER_ID`, `HCTI_API_KEY` |
| **存放位置** | `workspace/secrets/provider.env` |
| **備註** | `image-generation` skill 需要；免費方案 50 張/月 |

---

## 快速驗證

設定完成後，用 `doctor.sh` 檢查 secrets 狀態：

```bash
./scripts/doctor.sh ~/bulls/<instance-id>
```

Check 7 (`secrets_readiness`) 會告訴你哪些 key 缺失。
