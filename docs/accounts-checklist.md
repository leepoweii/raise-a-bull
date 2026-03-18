# Accounts & Services Checklist

> AI agent 可讀的帳號/服務清單。每個項目列出：服務名稱、註冊網址、需要取得的資料、對應的環境變數、存放位置。

---

## Required（必填）— AI 模型認證

> **重要：** 使用 OAuth 登入是推薦方式，不需要手動填 API key。

### 方式 A：ChatGPT OAuth（推薦）

| 項目 | 內容 |
|---|---|
| **服務** | OpenAI ChatGPT（透過 OpenClaw OAuth） |
| **前置條件** | ChatGPT Plus 帳號（$20/月） |
| **設定方式** | 容器啟動後執行 `openclaw models auth login --provider openai-codex` |
| **流程** | 1. 執行指令 → 2. 終端機印出 URL → 3. 在任意瀏覽器打開 URL → 4. 登入 ChatGPT → 5. 把 redirect URL 貼回終端機 |
| **存放位置** | OpenClaw 自動管理（不需手動填 .env） |
| **備註** | 成熟穩定，OpenClaw 官方支援最完整 |

### 方式 B：Google Gemini OAuth（替代方案）

| 項目 | 內容 |
|---|---|
| **服務** | Google Gemini CLI |
| **前置條件** | Google 帳號 |
| **設定方式** | 容器啟動後執行 `openclaw models auth login --provider google-gemini-cli` |
| **流程** | 同上：執行指令 → 印 URL → 瀏覽器登入 → 貼回 redirect URL |
| **存放位置** | OpenClaw 自動管理 |
| **備註** | 門檻最低（只需 Google 帳號），但額度與穩定性政策可能變動 |

### 方式 C：OpenAI API Key（進階）

| 項目 | 內容 |
|---|---|
| **服務** | OpenAI API |
| **網址** | https://console.openai.com → API Keys |
| **取得** | API Key（以 `sk-` 開頭） |
| **環境變數** | `OPENAI_API_KEY` |
| **存放位置** | `workspace/secrets/provider.env` |
| **備註** | 適合有技術背景或需要 pay-per-use 控制成本的使用者 |

---

## Required — Google Workspace（Calendar / Tasks / Gmail）

| 項目 | 內容 |
|---|---|
| **服務** | Google Workspace（Calendar, Tasks, Gmail） |
| **前置條件** | Google 帳號 |
| **設定方式** | 容器內執行 `gog auth login`，同樣會印出 URL 在瀏覽器完成授權 |
| **存放位置** | gog CLI 自動管理 |
| **備註** | association / office preset 必須；bar / shop preset 選填 |

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
