# Channel Setup Guide — Discord & LINE

> 給 raise-a-bull 操作者的完整頻道設定指南。

---

## Discord Bot 設定

### 1. 建立 Discord Application

1. 前往 https://discord.com/developers/applications
2. 點 **New Application**
3. 輸入名稱（例如「小牛」），同意 ToS，點 **Create**
4. 記下以下資訊（Settings → General Information）：
   - **APPLICATION ID** → `DISCORD_APPLICATION_ID`
   - **PUBLIC KEY** → `DISCORD_PUBLIC_KEY`

### 2. 建立 Bot

1. 左側選 **Bot**
2. 點 **Reset Token**（或首次的 **Copy**）
3. 複製 Token → `DISCORD_BOT_TOKEN`
   > ⚠️ Token 只顯示一次，複製後立刻存到 `provider.env`

### 3. 設定 Bot 權限（Privileged Gateway Intents）

在 Bot 頁面往下滑到 **Privileged Gateway Intents**，開啟：

- [x] **MESSAGE CONTENT INTENT** — 必須，讓 bot 讀取訊息內容
- [x] **SERVER MEMBERS INTENT** — 選填，如果需要辨識成員
- [x] **PRESENCE INTENT** — 選填，通常不需要

點 **Save Changes**。

### 4. 設定 OAuth2 權限

1. 左側選 **OAuth2**
2. 記下：
   - **CLIENT ID** → `DISCORD_CLIENT_ID`（同 APPLICATION ID）
   - **CLIENT SECRET** → `DISCORD_CLIENT_SECRET`

### 5. 邀請 Bot 到 Server

1. 左側選 **OAuth2 → URL Generator**
2. Scopes 勾選：`bot`
3. Bot Permissions 勾選：
   - [x] Send Messages
   - [x] Read Message History
   - [x] View Channels
   - [x] Embed Links（選填，發送 rich embed）
   - [x] Attach Files（選填，傳送檔案）
   - [x] Add Reactions（選填）
4. 複製底部的 **Generated URL**
5. 在瀏覽器打開 URL，選擇你的 Server，點 **Authorize**

### 6. 建立 Server 和 Channel（如果還沒有）

1. Discord 左側 **+** → Create My Own → For me and my friends
2. 預設會有 `#general` channel
3. 記下 Channel Link（右鍵 channel → Copy Channel Link）
   - 格式：`https://discord.com/channels/{SERVER_ID}/{CHANNEL_ID}`

### 7. 寫入 provider.env

```bash
# 在 workspace/secrets/provider.env 加入：
DISCORD_BOT_TOKEN=你的bot.token
DISCORD_APPLICATION_ID=你的application_id
DISCORD_PUBLIC_KEY=你的public_key
DISCORD_CLIENT_ID=你的client_id
DISCORD_CLIENT_SECRET=你的client_secret
```

### 8. 啟用 OpenClaw Discord Plugin

```bash
# 在容器內執行：
openclaw plugins enable discord

# 重建容器以載入新 env vars（docker restart 不會重新讀取 env_file）：
cd ~/bulls/<instance-id>
docker compose up -d --force-recreate

# 驗證 Discord 連線：
docker logs bull-<instance-id> --tail 20 | grep discord
# 應該看到: [discord] logged in to discord as <bot_id> (<bot_name>)
```

### 9. Discord DM 安全政策

OpenClaw 預設鎖定 Discord DM（`channels.discord.dm.policy="pairing"`）。

- 未知使用者傳 DM 給 bot 會被擋住，需要 pairing code
- 管理 pairing：
  ```bash
  openclaw pairing list discord        # 查看待審核的配對
  openclaw pairing approve discord <code>  # 核准配對
  ```
- 如果只在 server channel 使用（不需 DM），可以忽略此設定

### 重要注意事項

- `docker restart` **不會**重新讀取 `env_file`。修改 `provider.env` 後必須用 `docker compose up -d --force-recreate`
- Bot Token 洩漏後應立即在 Developer Portal 重置
- 100 server 以下的 bot 不需要通過 Discord 驗證就能用 Message Content Intent

---

## LINE Messaging API 設定

### 1. 建立 LINE Channel

1. 前往 https://developers.line.biz/console/
2. 登入 LINE 帳號（或建立 LINE Business ID）
3. 建立 Provider（如果沒有）
4. 點 **Create a new channel** → 選 **Messaging API**
5. 填寫資料：
   - Channel name（例如「小牛」）
   - Channel description
   - Category / Subcategory
   - 同意條款，點 **Create**

### 2. 取得 Channel Secret

1. 進入剛建立的 Channel
2. 在 **Basic settings** 頁面
3. 找到 **Channel secret** → 複製
   → `LINE_CHANNEL_SECRET`

### 3. 取得 Channel Access Token

1. 切到 **Messaging API** 分頁
2. 滑到最下方 **Channel access token**
3. 點 **Issue**（首次）或 **Reissue**
4. 複製長串 token
   → `LINE_CHANNEL_ACCESS_TOKEN`

### 4. 設定 Webhook URL

1. 在 **Messaging API** 分頁
2. 找到 **Webhook URL**
3. 填入你的 OpenClaw 公開 URL：
   ```
   https://your-domain.com/webhook/line
   ```
   > ⚠️ LINE webhook 需要公開 HTTPS URL。如果在內網，需要用 ngrok、Cloudflare Tunnel 等反向代理
4. 點 **Verify** 確認連線成功
5. 開啟 **Use webhook**

### 5. 關閉自動回覆

1. 在 **Messaging API** 分頁
2. 找到 **LINE Official Account features**
3. 點 **Auto-reply messages** → 進入設定頁面
4. 關閉 **Auto-reply** 和 **Greeting messages**
   > 不關閉的話，LINE 官方帳號會自動回覆，跟 OpenClaw 的回覆重疊

### 6. 寫入 provider.env

```bash
# 在 workspace/secrets/provider.env 加入：
LINE_CHANNEL_SECRET=你的channel_secret
LINE_CHANNEL_ACCESS_TOKEN=你的channel_access_token
```

### 7. 啟用 OpenClaw LINE Plugin

```bash
# 在容器內執行：
openclaw plugins enable line

# 重建容器：
cd ~/bulls/<instance-id>
docker compose up -d --force-recreate

# 驗證：
docker logs bull-<instance-id> --tail 20 | grep line
```

### LINE 注意事項

- LINE Messaging API 免費方案每月 **200 則**推播訊息（2024 年起）
- 回覆訊息（reply）不計入額度，只有主動推播（push）才計
- Channel Access Token 有效期限很長，但可隨時 Reissue（舊的會失效）
- LINE webhook 必須是 **HTTPS**，自簽憑證不行

---

## 環境變數載入重點

```
workspace/secrets/provider.env    ← 所有 channel 的 credentials
docker-compose.yml env_file      ← 指向 provider.env
```

**修改 provider.env 後的正確重啟流程：**

```bash
cd ~/bulls/<instance-id>
docker compose up -d --force-recreate
```

`docker restart` 只重啟 process，不會重新讀取 env_file 內的變數。

---

## 快速驗證清單

| 項目 | 指令 | 預期結果 |
|------|------|----------|
| Discord env loaded | `docker exec bull-<id> env \| grep DISCORD_BOT_TOKEN` | 有值 |
| Discord connected | `docker logs bull-<id> --tail 30 \| grep discord` | `logged in to discord as ...` |
| LINE env loaded | `docker exec bull-<id> env \| grep LINE_CHANNEL` | 有值 |
| LINE webhook | 在 LINE Developer Console 點 Verify | 成功 |
| Overall health | `docker exec bull-<id> openclaw doctor` | 無 CRITICAL |

---

*建立於：2026-03-13*
