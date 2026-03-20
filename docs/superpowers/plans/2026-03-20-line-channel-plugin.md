# LINE Channel Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone LINE Messaging API channel plugin for Claude Code, following Anthropic's Discord/Telegram plugin patterns.

**Architecture:** Two-file split — `server.ts` (MCP server, access control, tools) imports `line.ts` (Bun HTTP server, LINE API, auto-tunnel). The MCP server connects to Claude Code via stdio transport. LINE webhooks arrive on a Bun HTTP server running concurrently. Auto-tunnel via cloudflared provides zero-config webhook exposure.

**Tech Stack:** Bun runtime, `@modelcontextprotocol/sdk`, `@line/bot-sdk`, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-20-line-channel-plugin-design.md`

---

## File Structure

```
plugins/line/
├── .claude-plugin/
│   └── plugin.json              # Plugin metadata
├── .mcp.json                    # MCP server launch command
├── server.ts                    # MCP server, access control, tools, chunking (~400 lines)
├── line.ts                      # Bun HTTP, LINE API, tunnel, token cache (~350 lines)
├── access.ts                    # Access control: read/write access.json, gate, pairing (~200 lines)
├── package.json                 # Dependencies + start script
├── tsconfig.json                # TypeScript config
├── README.md                    # Setup guide
├── ACCESS.md                    # Access control docs
├── skills/
│   ├── access/SKILL.md          # /line:access skill
│   └── configure/SKILL.md       # /line:configure skill
├── LICENSE                      # Apache 2.0
└── __tests__/
    ├── access.test.ts           # Unit: gate function, pairing, allowlist
    ├── chunking.test.ts         # Unit: message chunking
    ├── token-cache.test.ts      # Unit: reply token cache
    ├── webhook.test.ts          # Unit: webhook signature verification, event parsing
    └── gate-filter.test.ts      # Unit: group filtering (mention, prefix)
```

**Note:** `access.ts` is extracted from `server.ts` for testability. The spec says two files (`server.ts` + `line.ts`), but access control logic is complex enough to warrant its own module. `server.ts` imports and uses it.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `plugins/line/package.json`
- Create: `plugins/line/tsconfig.json`
- Create: `plugins/line/.claude-plugin/plugin.json`
- Create: `plugins/line/.mcp.json`

- [ ] **Step 1: Install bun (if not present)**

```bash
# macOS
brew install oven-sh/bun/bun
# Verify
bun --version
```

- [ ] **Step 2: Create plugins/line directory and package.json**

```json
{
  "name": "claude-channel-line",
  "version": "0.1.0",
  "description": "LINE Messaging API channel plugin for Claude Code",
  "scripts": {
    "start": "bun server.ts",
    "setup": "bun install --no-summary",
    "test": "bun test"
  },
  "dependencies": {
    "@line/bot-sdk": "^9.0.0",
    "@modelcontextprotocol/sdk": "^1.12.1"
  },
  "devDependencies": {
    "@types/bun": "latest"
  }
}
```

- [ ] **Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "./dist",
    "rootDir": ".",
    "types": ["bun"]
  },
  "include": ["*.ts", "__tests__/*.ts"]
}
```

- [ ] **Step 4: Create .claude-plugin/plugin.json**

```json
{
  "name": "claude-channel-line",
  "description": "LINE Messaging API channel plugin for Claude Code — receive and send LINE messages from a persistent Claude Code session",
  "author": {
    "name": "pwlee"
  },
  "version": "0.1.0"
}
```

- [ ] **Step 5: Create .mcp.json**

```json
{
  "line": {
    "command": "bun",
    "args": ["run", "--cwd", "${CLAUDE_PLUGIN_ROOT}", "--silent", "start"]
  }
}
```

- [ ] **Step 6: Create .gitignore**

```
node_modules/
dist/
```

- [ ] **Step 7: Run bun install**

```bash
cd plugins/line && bun install
```

Expected: `bun.lock` created, `node_modules/` populated.

- [ ] **Step 8: Commit**

```bash
git add plugins/line/package.json plugins/line/tsconfig.json plugins/line/.claude-plugin/plugin.json plugins/line/.mcp.json plugins/line/.gitignore plugins/line/bun.lock
git commit -m "feat(line-plugin): scaffold project with dependencies"
```

---

## Task 2: Access Control Module

**Files:**
- Create: `plugins/line/access.ts`
- Create: `plugins/line/__tests__/access.test.ts`

This is the core gating logic. Build it first because everything else depends on it.

- [ ] **Step 1: Write failing tests for access control**

```typescript
// __tests__/access.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'bun:test'
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'fs'
import {
  loadAccess,
  saveAccess,
  isUserAllowed,
  isGroupEnabled,
  createPairingCode,
  approvePairing,
  addToAllowlist,
  removeFromAllowlist,
  defaultAccess,
  type AccessConfig,
} from '../access'

const TEST_DIR = '/tmp/test-line-access'
const ACCESS_PATH = `${TEST_DIR}/access.json`

beforeEach(() => {
  mkdirSync(TEST_DIR, { recursive: true })
})

afterEach(() => {
  rmSync(TEST_DIR, { recursive: true, force: true })
})

describe('loadAccess', () => {
  it('returns default config when file does not exist', () => {
    const config = loadAccess(ACCESS_PATH)
    expect(config.dms.policy).toBe('pairing')
    expect(config.dms.allowlist).toEqual([])
    expect(config.groups).toEqual({})
  })

  it('reads existing config from file', () => {
    const existing: AccessConfig = {
      dms: { policy: 'allowlist', allowlist: ['U123'], pairing: {} },
      groups: { 'C456': { enabled: true, requireMention: true } },
    }
    writeFileSync(ACCESS_PATH, JSON.stringify(existing))
    const config = loadAccess(ACCESS_PATH)
    expect(config.dms.policy).toBe('allowlist')
    expect(config.dms.allowlist).toContain('U123')
  })
})

describe('isUserAllowed', () => {
  it('allows users in allowlist', () => {
    const config = defaultAccess()
    config.dms.allowlist = ['U123']
    expect(isUserAllowed(config, 'U123')).toBe(true)
  })

  it('denies users not in allowlist', () => {
    const config = defaultAccess()
    expect(isUserAllowed(config, 'U999')).toBe(false)
  })
})

describe('isGroupEnabled', () => {
  it('returns false for unknown groups', () => {
    const config = defaultAccess()
    expect(isGroupEnabled(config, 'C999')).toBe(false)
  })

  it('returns true for enabled groups', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true }
    expect(isGroupEnabled(config, 'C123')).toBe(true)
  })
})

describe('createPairingCode', () => {
  it('generates a 6-char hex code', () => {
    const config = defaultAccess()
    const code = createPairingCode(config, 'U789')
    expect(code).toMatch(/^[0-9a-f]{6}$/)
    expect(config.dms.pairing[code]).toBeDefined()
    expect(config.dms.pairing[code].user_id).toBe('U789')
  })

  it('sets 1-hour expiry', () => {
    const config = defaultAccess()
    const code = createPairingCode(config, 'U789')
    const expires = new Date(config.dms.pairing[code].expires)
    const now = new Date()
    const diffMs = expires.getTime() - now.getTime()
    // Should be ~1 hour (3600000ms), allow 5s tolerance
    expect(diffMs).toBeGreaterThan(3595000)
    expect(diffMs).toBeLessThan(3605000)
  })
})

describe('approvePairing', () => {
  it('moves user from pairing to allowlist', () => {
    const config = defaultAccess()
    const code = createPairingCode(config, 'U789')
    const result = approvePairing(config, code)
    expect(result).toBe(true)
    expect(config.dms.allowlist).toContain('U789')
    expect(config.dms.pairing[code]).toBeUndefined()
  })

  it('returns false for invalid code', () => {
    const config = defaultAccess()
    expect(approvePairing(config, 'invalid')).toBe(false)
  })

  it('returns false for expired code', () => {
    const config = defaultAccess()
    const code = createPairingCode(config, 'U789')
    // Manually expire it
    config.dms.pairing[code].expires = new Date(Date.now() - 1000).toISOString()
    expect(approvePairing(config, code)).toBe(false)
  })
})

describe('addToAllowlist / removeFromAllowlist', () => {
  it('adds user to allowlist', () => {
    const config = defaultAccess()
    addToAllowlist(config, 'U123')
    expect(config.dms.allowlist).toContain('U123')
  })

  it('adds group to groups', () => {
    const config = defaultAccess()
    addToAllowlist(config, 'C456')
    expect(config.groups['C456']).toBeDefined()
    expect(config.groups['C456'].enabled).toBe(true)
    expect(config.groups['C456'].requireMention).toBe(true)
  })

  it('removes user from allowlist', () => {
    const config = defaultAccess()
    config.dms.allowlist = ['U123']
    removeFromAllowlist(config, 'U123')
    expect(config.dms.allowlist).not.toContain('U123')
  })

  it('disables group', () => {
    const config = defaultAccess()
    config.groups['C456'] = { enabled: true, requireMention: true }
    removeFromAllowlist(config, 'C456')
    expect(config.groups['C456'].enabled).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd plugins/line && bun test __tests__/access.test.ts
```

Expected: FAIL — `access` module doesn't exist.

- [ ] **Step 3: Implement access.ts**

```typescript
// access.ts
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { randomBytes } from 'crypto'

export interface GroupConfig {
  enabled: boolean
  requireMention: boolean
  triggerPrefix?: string
}

export interface PairingEntry {
  user_id: string
  expires: string // ISO8601
}

export interface AccessConfig {
  dms: {
    policy: 'pairing' | 'allowlist' | 'disabled'
    allowlist: string[]
    pairing: Record<string, PairingEntry>
  }
  groups: Record<string, GroupConfig>
}

export function defaultAccess(): AccessConfig {
  return {
    dms: { policy: 'pairing', allowlist: [], pairing: {} },
    groups: {},
  }
}

export function loadAccess(path: string): AccessConfig {
  if (!existsSync(path)) return defaultAccess()
  try {
    return JSON.parse(readFileSync(path, 'utf-8'))
  } catch {
    return defaultAccess()
  }
}

export function saveAccess(path: string, config: AccessConfig): void {
  writeFileSync(path, JSON.stringify(config, null, 2))
}

export function isUserAllowed(config: AccessConfig, userId: string): boolean {
  return config.dms.allowlist.includes(userId)
}

export function isGroupEnabled(config: AccessConfig, groupId: string): boolean {
  return config.groups[groupId]?.enabled === true
}

export function getGroupConfig(config: AccessConfig, groupId: string): GroupConfig | undefined {
  return config.groups[groupId]
}

export function createPairingCode(config: AccessConfig, userId: string): string {
  const code = randomBytes(3).toString('hex') // 6 hex chars
  const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString()
  config.dms.pairing[code] = { user_id: userId, expires }
  return code
}

export function approvePairing(config: AccessConfig, code: string): boolean {
  const entry = config.dms.pairing[code]
  if (!entry) return false
  if (new Date(entry.expires) < new Date()) {
    delete config.dms.pairing[code]
    return false
  }
  config.dms.allowlist.push(entry.user_id)
  delete config.dms.pairing[code]
  return true
}

export function addToAllowlist(config: AccessConfig, id: string): void {
  // Group IDs start with C, Room IDs with R
  if (id.startsWith('C') || id.startsWith('R')) {
    if (config.groups[id]) {
      config.groups[id].enabled = true // Preserve existing triggerPrefix/requireMention
    } else {
      config.groups[id] = { enabled: true, requireMention: true }
    }
  } else {
    if (!config.dms.allowlist.includes(id)) {
      config.dms.allowlist.push(id)
    }
  }
}

export function removeFromAllowlist(config: AccessConfig, id: string): void {
  if (id.startsWith('C') || id.startsWith('R')) {
    if (config.groups[id]) {
      config.groups[id].enabled = false
    }
  } else {
    config.dms.allowlist = config.dms.allowlist.filter((u) => u !== id)
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd plugins/line && bun test __tests__/access.test.ts
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/line/access.ts plugins/line/__tests__/access.test.ts
git commit -m "feat(line-plugin): access control module with pairing, allowlist, groups"
```

---

## Task 3: Group Message Filtering

**Files:**
- Create: `plugins/line/__tests__/gate-filter.test.ts`
- Modify: `plugins/line/access.ts` (add `shouldForwardGroupMessage`)

- [ ] **Step 1: Write failing tests for group filtering**

```typescript
// __tests__/gate-filter.test.ts
import { describe, it, expect } from 'bun:test'
import { shouldForwardGroupMessage, defaultAccess, type AccessConfig } from '../access'

describe('shouldForwardGroupMessage', () => {
  it('rejects messages from unenabled groups', () => {
    const config = defaultAccess()
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(false)
  })

  it('forwards @mention when requireMention is true (default)', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', true)
    expect(result.forward).toBe(true)
  })

  it('rejects non-mention when requireMention is true', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(false)
  })

  it('forwards prefix match and strips prefix', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, triggerPrefix: '小助理' }
    const result = shouldForwardGroupMessage(config, 'C123', '小助理 help me', false)
    expect(result.forward).toBe(true)
    expect(result.text).toBe('help me')
  })

  it('rejects non-matching prefix', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, triggerPrefix: '小助理' }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(false)
  })

  it('prefix overrides requireMention', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, triggerPrefix: '小助理' }
    // Has prefix, not a mention — should still forward because prefix takes priority
    const result = shouldForwardGroupMessage(config, 'C123', '小助理 hello', false)
    expect(result.forward).toBe(true)
  })

  it('forwards all when requireMention false and no prefix', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: false }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(true)
    expect(result.text).toBe('hello')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd plugins/line && bun test __tests__/gate-filter.test.ts
```

Expected: FAIL — `shouldForwardGroupMessage` doesn't exist.

- [ ] **Step 3: Add shouldForwardGroupMessage to access.ts**

Add to bottom of `access.ts`:

```typescript
export interface FilterResult {
  forward: boolean
  text?: string
}

export function shouldForwardGroupMessage(
  config: AccessConfig,
  groupId: string,
  text: string,
  isMention: boolean
): FilterResult {
  const group = config.groups[groupId]
  if (!group?.enabled) return { forward: false }

  // triggerPrefix takes priority over requireMention
  if (group.triggerPrefix) {
    if (text.startsWith(group.triggerPrefix)) {
      return { forward: true, text: text.slice(group.triggerPrefix.length).trim() }
    }
    return { forward: false }
  }

  // requireMention (default true)
  if (group.requireMention !== false) {
    return isMention ? { forward: true, text } : { forward: false }
  }

  // requireMention: false, no prefix — forward all
  return { forward: true, text }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd plugins/line && bun test __tests__/gate-filter.test.ts
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/line/access.ts plugins/line/__tests__/gate-filter.test.ts
git commit -m "feat(line-plugin): group message filtering with mention/prefix support"
```

---

## Task 4: Message Chunking

**Files:**
- Create: `plugins/line/__tests__/chunking.test.ts`
- Create: `plugins/line/chunking.ts`

LINE has a 5000-character limit per text message.

- [ ] **Step 1: Write failing tests**

```typescript
// __tests__/chunking.test.ts
import { describe, it, expect } from 'bun:test'
import { chunkMessage } from '../chunking'

describe('chunkMessage', () => {
  it('returns single chunk for short messages', () => {
    const chunks = chunkMessage('hello', 5000)
    expect(chunks).toEqual(['hello'])
  })

  it('splits on paragraph boundaries', () => {
    const text = 'paragraph one\n\nparagraph two\n\nparagraph three'
    // Force split after ~25 chars
    const chunks = chunkMessage(text, 30)
    expect(chunks.length).toBeGreaterThan(1)
    // Each chunk should be <= limit
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(30)
    }
  })

  it('splits on newline if no paragraph break fits', () => {
    const text = 'line one\nline two\nline three\nline four'
    const chunks = chunkMessage(text, 20)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(20)
    }
  })

  it('hard splits if no break point found', () => {
    const text = 'a'.repeat(100)
    const chunks = chunkMessage(text, 30)
    expect(chunks.length).toBe(4) // 30 + 30 + 30 + 10
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(30)
    }
  })

  it('handles empty string', () => {
    expect(chunkMessage('', 5000)).toEqual([''])
  })

  it('defaults to LINE 5000 char limit', () => {
    const text = 'a'.repeat(10000)
    const chunks = chunkMessage(text)
    expect(chunks.length).toBe(2)
    expect(chunks[0].length).toBe(5000)
    expect(chunks[1].length).toBe(5000)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd plugins/line && bun test __tests__/chunking.test.ts
```

- [ ] **Step 3: Implement chunking.ts**

```typescript
// chunking.ts
const LINE_MAX_LENGTH = 5000

export function chunkMessage(text: string, maxLength = LINE_MAX_LENGTH): string[] {
  if (text.length <= maxLength) return [text]

  const chunks: string[] = []
  let remaining = text

  while (remaining.length > 0) {
    if (remaining.length <= maxLength) {
      chunks.push(remaining)
      break
    }

    let splitAt = -1
    const window = remaining.slice(0, maxLength)

    // Try paragraph break
    const paraBreak = window.lastIndexOf('\n\n')
    if (paraBreak > 0) {
      splitAt = paraBreak
    }

    // Try newline
    if (splitAt === -1) {
      const newline = window.lastIndexOf('\n')
      if (newline > 0) {
        splitAt = newline
      }
    }

    // Hard split
    if (splitAt === -1) {
      splitAt = maxLength
    }

    chunks.push(remaining.slice(0, splitAt))
    remaining = remaining.slice(splitAt).replace(/^\n+/, '')
  }

  return chunks
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd plugins/line && bun test __tests__/chunking.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add plugins/line/chunking.ts plugins/line/__tests__/chunking.test.ts
git commit -m "feat(line-plugin): message chunking for LINE 5000-char limit"
```

---

## Task 5: Reply Token Cache

**Files:**
- Create: `plugins/line/__tests__/token-cache.test.ts`
- Create: `plugins/line/token-cache.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// __tests__/token-cache.test.ts
import { describe, it, expect } from 'bun:test'
import { TokenCache } from '../token-cache'

describe('TokenCache', () => {
  it('stores and retrieves token by message_id', () => {
    const cache = new TokenCache()
    cache.set('msg1', 'Uabc', 'token123')
    const entry = cache.get('msg1')
    expect(entry).toBeDefined()
    expect(entry!.chatId).toBe('Uabc')
    expect(entry!.replyToken).toBe('token123')
  })

  it('returns undefined for unknown message_id', () => {
    const cache = new TokenCache()
    expect(cache.get('unknown')).toBeUndefined()
  })

  it('removes token after consume', () => {
    const cache = new TokenCache()
    cache.set('msg1', 'Uabc', 'token123')
    cache.consume('msg1')
    expect(cache.get('msg1')).toBeUndefined()
  })

  it('keeps multiple tokens for different messages', () => {
    const cache = new TokenCache()
    cache.set('msg1', 'Uabc', 'token1')
    cache.set('msg2', 'Uabc', 'token2')
    expect(cache.get('msg1')!.replyToken).toBe('token1')
    expect(cache.get('msg2')!.replyToken).toBe('token2')
  })

  it('cleans expired tokens (older than 60s)', () => {
    const cache = new TokenCache()
    // Manually set an old entry
    cache.set('old', 'Uabc', 'oldtoken')
    // Hack the timestamp to be 2 minutes ago
    cache['entries'].get('old')!.timestamp = Date.now() - 120_000
    cache.set('new', 'Uabc', 'newtoken')
    cache.cleanup()
    expect(cache.get('old')).toBeUndefined()
    expect(cache.get('new')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd plugins/line && bun test __tests__/token-cache.test.ts
```

- [ ] **Step 3: Implement token-cache.ts**

```typescript
// token-cache.ts
interface CacheEntry {
  chatId: string
  replyToken: string
  timestamp: number
}

const TOKEN_TTL_MS = 60_000 // 60 seconds — LINE tokens expire ~30s but we keep buffer

export class TokenCache {
  private entries = new Map<string, CacheEntry>()

  set(messageId: string, chatId: string, replyToken: string): void {
    this.entries.set(messageId, { chatId, replyToken, timestamp: Date.now() })
  }

  get(messageId: string): { chatId: string; replyToken: string } | undefined {
    const entry = this.entries.get(messageId)
    if (!entry) return undefined
    return { chatId: entry.chatId, replyToken: entry.replyToken }
  }

  consume(messageId: string): void {
    this.entries.delete(messageId)
  }

  cleanup(): void {
    const now = Date.now()
    for (const [id, entry] of this.entries) {
      if (now - entry.timestamp > TOKEN_TTL_MS) {
        this.entries.delete(id)
      }
    }
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd plugins/line && bun test __tests__/token-cache.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add plugins/line/token-cache.ts plugins/line/__tests__/token-cache.test.ts
git commit -m "feat(line-plugin): reply token cache keyed by message_id"
```

---

## Task 6: LINE Platform Adapter (line.ts)

**Files:**
- Create: `plugins/line/line.ts`
- Create: `plugins/line/__tests__/webhook.test.ts`

This is the LINE-specific layer: Bun HTTP server, webhook verification, LINE API client, auto-tunnel.

- [ ] **Step 1: Write failing webhook tests**

```typescript
// __tests__/webhook.test.ts
import { describe, it, expect } from 'bun:test'
import { createHmac } from 'crypto'
import { validateSignature } from '@line/bot-sdk'
import { formatInboundContent } from '../line'

const TEST_SECRET = 'test-channel-secret'

function sign(body: string, secret: string): string {
  return createHmac('sha256', secret).update(body).digest('base64')
}

describe('validateSignature (from @line/bot-sdk)', () => {
  it('accepts valid signature', () => {
    const body = '{"events":[]}'
    const signature = sign(body, TEST_SECRET)
    expect(validateSignature(body, TEST_SECRET, signature)).toBe(true)
  })

  it('rejects invalid signature', () => {
    const body = '{"events":[]}'
    expect(validateSignature(body, TEST_SECRET, 'invalid')).toBe(false)
  })

  it('rejects tampered body', () => {
    const body = '{"events":[]}'
    const signature = sign(body, TEST_SECRET)
    expect(validateSignature('{"events":[{}]}', TEST_SECRET, signature)).toBe(false)
  })
})

describe('formatInboundContent', () => {
  it('formats text message', () => {
    const event = {
      type: 'message',
      message: { type: 'text', id: 'msg1', text: 'hello world' },
    }
    expect(formatInboundContent(event as any)).toBe('hello world')
  })

  it('formats sticker message', () => {
    const event = {
      type: 'message',
      message: { type: 'sticker', id: 'msg2', packageId: '1', stickerId: '2' },
    }
    expect(formatInboundContent(event as any)).toBe('(sticker: package=1, id=2)')
  })

  it('formats location message', () => {
    const event = {
      type: 'message',
      message: {
        type: 'location',
        id: 'msg3',
        title: 'Tokyo Tower',
        address: 'Minato, Tokyo',
        latitude: 35.6586,
        longitude: 139.7454,
      },
    }
    const content = formatInboundContent(event as any)
    expect(content).toContain('Tokyo Tower')
    expect(content).toContain('35.6586')
  })

  it('formats image with external provider', () => {
    const event = {
      type: 'message',
      message: {
        type: 'image',
        id: 'msg4',
        contentProvider: { type: 'external', originalContentUrl: 'https://example.com/img.jpg' },
      },
    }
    expect(formatInboundContent(event as any)).toContain('https://example.com/img.jpg')
  })

  it('formats image with line provider as pending download', () => {
    const event = {
      type: 'message',
      message: {
        type: 'image',
        id: 'msg5',
        contentProvider: { type: 'line' },
      },
    }
    expect(formatInboundContent(event as any)).toContain('msg5')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd plugins/line && bun test __tests__/webhook.test.ts
```

- [ ] **Step 3: Implement line.ts**

Create `line.ts` with the full LINE adapter. Key sections:

```typescript
// line.ts
import { validateSignature, messagingApi, type WebhookEvent, type MessageEvent } from '@line/bot-sdk'
import { TokenCache } from './token-cache'
import { chunkMessage } from './chunking'

const { MessagingApiClient, MessagingApiBlobClient } = messagingApi

// --- Types ---

export interface LineConfig {
  channelSecret: string
  channelAccessToken: string
  port: number
  tunnelUrl?: string   // --tunnel-url: skip cloudflared
  noTunnel?: boolean   // --no-tunnel: skip tunnel entirely
  inboxDir: string     // Path for downloaded images
}

export interface InboundMessage {
  chatId: string
  messageId: string
  userId: string
  text: string
  messageType: string
  replyToken?: string
  timestamp: string
  mentionedUserIds?: string[] // from LINE mention event data
}

export interface LineCallbacks {
  onMessage: (msg: InboundMessage) => void | Promise<void>
  onFollow: (userId: string) => void
  onJoin: (groupId: string) => void
  onLeave: (groupId: string) => void
}

// --- Signature Verification ---
// Uses @line/bot-sdk's validateSignature (timing-safe comparison)
// Re-exported for convenience: validateSignature(body, secret, signature) => boolean

// --- Message Formatting ---

export function formatInboundContent(event: MessageEvent): string {
  const msg = event.message
  switch (msg.type) {
    case 'text':
      return msg.text
    case 'sticker':
      return `(sticker: package=${msg.packageId}, id=${msg.stickerId})`
    case 'location':
      return `(location: ${msg.title || ''} ${msg.address || ''} [${msg.latitude}, ${msg.longitude}])`
    case 'image': {
      const provider = msg.contentProvider
      if (provider.type === 'external') {
        return `(image: ${(provider as { originalContentUrl: string }).originalContentUrl})`
      }
      return `(image: pending download, message_id=${msg.id})`
    }
    default:
      return `(${msg.type} message)`
  }
}

// --- LINE API Client Wrapper ---

export class LineClient {
  private client: InstanceType<typeof MessagingApiClient>
  private blobClient: InstanceType<typeof MessagingApiBlobClient>
  private tokenCache: TokenCache

  constructor(accessToken: string) {
    this.client = new MessagingApiClient({ channelAccessToken: accessToken })
    this.blobClient = new MessagingApiBlobClient({ channelAccessToken: accessToken })
    this.tokenCache = new TokenCache()
  }

  cacheReplyToken(messageId: string, chatId: string, replyToken: string): void {
    this.tokenCache.set(messageId, chatId, replyToken)
  }

  async reply(chatId: string, text: string, replyTo: string): Promise<void> {
    const chunks = chunkMessage(text)
    const messages = chunks.map((c) => ({ type: 'text' as const, text: c }))

    const cached = this.tokenCache.get(replyTo)
    if (cached) {
      try {
        await this.client.replyMessage({ replyToken: cached.replyToken, messages })
        this.tokenCache.consume(replyTo)
        return
      } catch {
        // Token expired, fall through to push
        this.tokenCache.consume(replyTo)
      }
    }

    // Fallback to push
    await this.client.pushMessage({ to: chatId, messages })
  }

  async pushMessage(chatId: string, text: string): Promise<void> {
    const chunks = chunkMessage(text)
    const messages = chunks.map((c) => ({ type: 'text' as const, text: c }))
    await this.client.pushMessage({ to: chatId, messages })
  }

  async getBotInfo(): Promise<{ userId: string; displayName: string }> {
    const info = await this.client.getBotInfo()
    return { userId: info.userId, displayName: info.displayName }
  }

  async getProfile(userId: string): Promise<{ displayName: string; pictureUrl?: string }> {
    const profile = await this.client.getProfile(userId)
    return { displayName: profile.displayName, pictureUrl: profile.pictureUrl }
  }

  async setWebhookUrl(url: string): Promise<void> {
    await this.client.setWebhookEndpointUrl({ endpoint: url })
  }

  async testWebhook(): Promise<boolean> {
    try {
      await this.client.testWebhookEndpoint()
      return true
    } catch {
      return false
    }
  }

  async downloadImage(messageId: string, inboxDir: string): Promise<string> {
    const { mkdirSync } = await import('fs')
    mkdirSync(inboxDir, { recursive: true })
    const stream = await this.blobClient.getMessageContent(messageId)
    const path = `${inboxDir}/${messageId}.jpg`
    // Stream is a Readable — collect to buffer
    const chunks: Buffer[] = []
    for await (const chunk of stream as any) {
      chunks.push(Buffer.from(chunk))
    }
    await Bun.write(path, Buffer.concat(chunks))
    return path
  }

  cleanupTokens(): void {
    this.tokenCache.cleanup()
  }
}

// --- Extract chat/user IDs from webhook event ---

export function extractIds(event: WebhookEvent): { chatId: string; userId: string } | null {
  const source = event.source
  if (!source) return null
  const userId = source.userId || 'unknown'
  switch (source.type) {
    case 'user':
      return { chatId: userId, userId }
    case 'group':
      return { chatId: source.groupId!, userId }
    case 'room':
      return { chatId: source.roomId!, userId }
    default:
      return null
  }
}

// --- Auto-Tunnel ---

let tunnelProcess: ReturnType<typeof Bun.spawn> | null = null

export async function startTunnel(port: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = Bun.spawn(['cloudflared', 'tunnel', '--url', `http://localhost:${port}`], {
      stderr: 'pipe',
    })
    tunnelProcess = proc

    const timeout = setTimeout(() => {
      reject(new Error('Tunnel startup timed out after 15s'))
    }, 15_000)

    const reader = proc.stderr.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const readLoop = async () => {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const match = buffer.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/)
        if (match) {
          clearTimeout(timeout)
          resolve(match[0])
          return
        }
      }
    }
    readLoop().catch(reject)
  })
}

export function stopTunnel(): void {
  if (tunnelProcess) {
    tunnelProcess.kill()
    tunnelProcess = null
  }
}

// --- Bun HTTP Server ---

export function startHttpServer(
  config: LineConfig,
  callbacks: LineCallbacks
): { server: ReturnType<typeof Bun.serve> } {
  const server = Bun.serve({
    port: config.port,
    async fetch(req) {
      const url = new URL(req.url)

      if (url.pathname === '/health') {
        return new Response(JSON.stringify({ status: 'ok' }), {
          headers: { 'content-type': 'application/json' },
        })
      }

      if (url.pathname === '/webhook' && req.method === 'POST') {
        const body = await req.text()
        const signature = req.headers.get('x-line-signature') || ''

        if (!validateSignature(body, config.channelSecret, signature)) {
          // Return 200 anyway — LINE retries on non-200
          return new Response('OK', { status: 200 })
        }

        try {
          const parsed = JSON.parse(body)
          const events: WebhookEvent[] = parsed.events || []

          for (const event of events) {
            const ids = extractIds(event)
            if (!ids) continue

            switch (event.type) {
              case 'message': {
                const content = formatInboundContent(event as MessageEvent)
                const msgEvent = event as MessageEvent
                // Extract mention data from text messages
                const mentionedUserIds = msgEvent.message.type === 'text'
                  && (msgEvent.message as any).mention?.mentionees
                  ? (msgEvent.message as any).mention.mentionees.map((m: any) => m.userId).filter(Boolean)
                  : undefined
                callbacks.onMessage({
                  chatId: ids.chatId,
                  messageId: msgEvent.message.id,
                  userId: ids.userId,
                  text: content,
                  messageType: msgEvent.message.type,
                  replyToken: event.replyToken,
                  timestamp: new Date(event.timestamp).toISOString(),
                  mentionedUserIds,
                })
                break
              }
              case 'follow':
                callbacks.onFollow(ids.userId)
                break
              case 'join':
                callbacks.onJoin(ids.chatId)
                break
              case 'leave':
                callbacks.onLeave(ids.chatId)
                break
            }
          }
        } catch {
          // Parse error — still return 200
        }

        return new Response('OK', { status: 200 })
      }

      return new Response('Not Found', { status: 404 })
    },
  })

  return { server }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd plugins/line && bun test __tests__/webhook.test.ts
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/line/line.ts plugins/line/__tests__/webhook.test.ts
git commit -m "feat(line-plugin): LINE platform adapter with HTTP server, webhook, tunnel"
```

---

## Task 7: MCP Server (server.ts)

**Files:**
- Create: `plugins/line/server.ts`

This is the main entry point. Connects MCP to Claude Code via stdio, registers tools, wires up access control and the LINE adapter.

- [ ] **Step 1: Implement server.ts**

```typescript
// server.ts
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { homedir } from 'os'
import { join } from 'path'
import { existsSync, mkdirSync, readFileSync } from 'fs'
import {
  loadAccess,
  saveAccess,
  isUserAllowed,
  isGroupEnabled,
  createPairingCode,
  approvePairing,
  addToAllowlist,
  removeFromAllowlist,
  shouldForwardGroupMessage,
  type AccessConfig,
} from './access'
import {
  LineClient,
  startHttpServer,
  startTunnel,
  stopTunnel,
  extractIds,
  type LineConfig,
  type InboundMessage,
} from './line'

// --- Config ---

const CHANNELS_DIR = join(homedir(), '.claude', 'channels', 'line')
const ACCESS_PATH = join(CHANNELS_DIR, 'access.json')
const ENV_PATH = join(CHANNELS_DIR, '.env')
const INBOX_DIR = join(CHANNELS_DIR, 'inbox')

function loadEnv(): { secret: string; token: string } | null {
  // Env vars take precedence
  const secret = process.env.LINE_CHANNEL_SECRET
  const token = process.env.LINE_CHANNEL_ACCESS_TOKEN
  if (secret && token) return { secret, token }

  // Try .env file
  if (!existsSync(ENV_PATH)) return null
  const content = readFileSync(ENV_PATH, 'utf-8')
  const vars: Record<string, string> = {}
  for (const line of content.split('\n')) {
    const match = line.match(/^(\w+)=(.*)$/)
    if (match) vars[match[1]] = match[2].replace(/^["']|["']$/g, '') // strip surrounding quotes
  }
  if (vars.LINE_CHANNEL_SECRET && vars.LINE_CHANNEL_ACCESS_TOKEN) {
    return { secret: vars.LINE_CHANNEL_SECRET, token: vars.LINE_CHANNEL_ACCESS_TOKEN }
  }
  return null
}

function parseArgs(): { port: number; tunnelUrl?: string; noTunnel?: boolean } {
  const args = process.argv.slice(2)
  let port = parseInt(process.env.LINE_PORT || '3000')
  let tunnelUrl: string | undefined
  let noTunnel = false

  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--port=')) port = parseInt(args[i].split('=')[1])
    else if (args[i] === '--port') port = parseInt(args[++i])
    else if (args[i].startsWith('--tunnel-url=')) tunnelUrl = args[i].split('=')[1]
    else if (args[i] === '--tunnel-url') tunnelUrl = args[++i]
    else if (args[i] === '--no-tunnel') noTunnel = true
  }

  return { port, tunnelUrl, noTunnel }
}

// --- Main ---

async function main() {
  // Ensure directories exist
  mkdirSync(CHANNELS_DIR, { recursive: true })
  mkdirSync(INBOX_DIR, { recursive: true })

  // Load credentials
  const env = loadEnv()
  if (!env) {
    console.error('No LINE credentials found. Run /line:configure token to set up.')
    console.error(`Or set LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN env vars.`)
    process.exit(1)
  }

  const { port, tunnelUrl, noTunnel } = parseArgs()

  // --- MCP Server ---

  const mcp = new Server(
    { name: 'line', version: '0.1.0' },
    {
      capabilities: {
        tools: {},
        experimental: { 'claude/channel': {} },
      },
    }
  )

  // --- LINE Client ---

  const lineClient = new LineClient(env.token)

  // Periodic token cleanup
  setInterval(() => lineClient.cleanupTokens(), 30_000)

  // Profile display name cache (userId → { name, fetchedAt })
  // TTL: 1 hour, max 1000 entries
  const profileCache = new Map<string, { name: string; fetchedAt: number }>()
  function getCachedProfile(userId: string): string | undefined {
    const entry = profileCache.get(userId)
    if (!entry) return undefined
    if (Date.now() - entry.fetchedAt > 3600_000) {
      profileCache.delete(userId)
      return undefined
    }
    return entry.name
  }
  function setCachedProfile(userId: string, name: string): void {
    if (profileCache.size >= 1000) {
      // Evict oldest
      const oldest = profileCache.keys().next().value
      if (oldest) profileCache.delete(oldest)
    }
    profileCache.set(userId, { name, fetchedAt: Date.now() })
  }

  // --- Access Control ---

  let access = loadAccess(ACCESS_PATH)

  function reloadAccess(): AccessConfig {
    access = loadAccess(ACCESS_PATH)
    return access
  }

  function persistAccess(): void {
    saveAccess(ACCESS_PATH, access)
  }

  // --- Tool Registration ---

  mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: 'reply',
        description: 'Reply to a LINE message. Uses reply token (free) if available, falls back to push API.',
        inputSchema: {
          type: 'object',
          properties: {
            chat_id: { type: 'string', description: 'User ID or Group ID' },
            text: { type: 'string', description: 'Message text' },
            reply_to: { type: 'string', description: 'message_id from the inbound notification to pair with reply token' },
          },
          required: ['chat_id', 'text', 'reply_to'],
        },
      },
      {
        name: 'push_message',
        description: 'Send a proactive message to a LINE user or group. Always uses push API (costs quota). Use for unsolicited messages where there is no recent inbound event.',
        inputSchema: {
          type: 'object',
          properties: {
            chat_id: { type: 'string', description: 'User ID or Group ID' },
            text: { type: 'string', description: 'Message text' },
          },
          required: ['chat_id', 'text'],
        },
      },
      {
        name: 'get_profile',
        description: 'Get a LINE user\'s display name and profile picture URL.',
        inputSchema: {
          type: 'object',
          properties: {
            user_id: { type: 'string', description: 'LINE User ID' },
          },
          required: ['user_id'],
        },
      },
    ],
  }))

  mcp.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params
    reloadAccess()

    try {
      switch (name) {
        case 'reply': {
          const { chat_id, text, reply_to } = args
          await lineClient.reply(chat_id, text, reply_to)
          return { content: [{ type: 'text', text: `Message sent to ${chat_id}` }] }
        }
        case 'push_message': {
          const { chat_id, text } = args
          await lineClient.pushMessage(chat_id, text)
          return { content: [{ type: 'text', text: `Push message sent to ${chat_id}` }] }
        }
        case 'get_profile': {
          const { user_id } = args
          const profile = await lineClient.getProfile(user_id)
          return {
            content: [{ type: 'text', text: JSON.stringify(profile, null, 2) }],
          }
        }
        default:
          return { content: [{ type: 'text', text: `Unknown tool: ${name}` }], isError: true }
      }
    } catch (err: any) {
      return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true }
    }
  })

  // --- Fetch bot's own user ID at startup (for mention detection in groups) ---

  let botUserId = process.env.LINE_BOT_USER_ID || ''
  if (!botUserId) {
    try {
      const botInfo = await lineClient.getBotInfo()
      botUserId = botInfo.userId
      console.error(`[line] Bot user ID: ${botUserId}`)
    } catch {
      console.error('[line] WARNING: Could not fetch bot info. Group @mention detection will not work.')
      console.error('[line] Set LINE_BOT_USER_ID in .env as fallback.')
    }
  }

  // --- Inbound Message Handler ---

  async function handleInbound(msg: InboundMessage): Promise<void> {
    reloadAccess()
    const isGroup = msg.chatId !== msg.userId

    if (isGroup) {
      if (!isGroupEnabled(access, msg.chatId)) {
        // Reply with group ID + instructions
        lineClient.pushMessage(
          msg.chatId,
          `I'm not enabled for this group yet.\nGroup ID: \`${msg.chatId}\`\nOwner: run \`/line:access allow ${msg.chatId}\``
        ).catch(() => {})
        return
      }

      // Check group filter
      // LINE provides mention data in message.mention.mentionees[] for text messages
      // Each mentionee has a userId — check if the bot's userId is mentioned
      const isMention = botUserId && msg.messageType === 'text' && msg.mentionedUserIds
        ? msg.mentionedUserIds.includes(botUserId)
        : false
      const filter = shouldForwardGroupMessage(access, msg.chatId, msg.text, isMention)
      if (!filter.forward) return
      if (filter.text !== undefined) msg.text = filter.text
    } else {
      // DM
      if (!isUserAllowed(access, msg.userId)) {
        if (access.dms.policy === 'pairing') {
          const code = createPairingCode(access, msg.userId)
          persistAccess()
          lineClient.pushMessage(
            msg.userId,
            `Hi! Pairing code: \`${code}\`\nYour user ID: \`${msg.userId}\`\nAsk the bot owner to run \`/line:access pair ${code}\` in Claude Code.`
          ).catch(() => {})
        } else if (access.dms.policy === 'allowlist') {
          lineClient.pushMessage(
            msg.userId,
            `I'm not set up to chat with you yet.\nYour user ID: \`${msg.userId}\`\nAsk the bot owner to run \`/line:access allow ${msg.userId}\``
          ).catch(() => {})
        }
        // policy === 'disabled' — silently drop
        return
      }
    }

    // Cache reply token
    if (msg.replyToken) {
      lineClient.cacheReplyToken(msg.messageId, msg.chatId, msg.replyToken)
    }

    // Resolve display name (cached with TTL to avoid API calls on every message)
    let displayName = getCachedProfile(msg.userId)
    if (!displayName) {
      try {
        const profile = await lineClient.getProfile(msg.userId)
        displayName = profile.displayName
        setCachedProfile(msg.userId, displayName)
      } catch {
        displayName = msg.userId // Fallback to raw ID
      }
    }

    // Forward to Claude Code via MCP notification
    void mcp.notification({
      method: 'notifications/claude/channel',
      params: {
        content: msg.text,
        meta: {
          chat_id: msg.chatId,
          message_id: msg.messageId,
          user: displayName,
          user_id: msg.userId,
          ts: msg.timestamp,
          message_type: msg.messageType,
        },
      },
    })
  }

  // --- Connect MCP FIRST (before HTTP server, so notifications work immediately) ---

  const transport = new StdioServerTransport()
  await mcp.connect(transport)

  // --- Start LINE HTTP Server ---

  const lineConfig: LineConfig = {
    channelSecret: env.secret,
    channelAccessToken: env.token,
    port,
    tunnelUrl,
    noTunnel,
    inboxDir: INBOX_DIR,
  }

  const { server } = startHttpServer(lineConfig, {
    onMessage: handleInbound,
    onFollow: (userId) => console.error(`[line] User followed: ${userId}`),
    onJoin: (groupId) => console.error(`[line] Bot joined group: ${groupId}`),
    onLeave: (groupId) => console.error(`[line] Bot left group: ${groupId}`),
  })

  console.error(`[line] HTTP server listening on port ${port}`)

  // --- Auto-Tunnel ---

  let webhookUrl: string

  if (tunnelUrl) {
    webhookUrl = `${tunnelUrl}/webhook`
    console.error(`[line] Using provided tunnel URL: ${webhookUrl}`)
  } else if (noTunnel) {
    webhookUrl = `http://localhost:${port}/webhook`
    console.error(`[line] No tunnel — webhook at ${webhookUrl}`)
  } else {
    // Check cloudflared is installed
    try {
      Bun.spawnSync(['cloudflared', '--version'])
    } catch {
      console.error('[line] ERROR: cloudflared not found. Install it: brew install cloudflared')
      console.error('[line] Or use --tunnel-url <url> / --no-tunnel to skip.')
      process.exit(1)
    }

    console.error('[line] Starting cloudflared tunnel...')
    const tunnelBase = await startTunnel(port)
    webhookUrl = `${tunnelBase}/webhook`
    console.error(`[line] Tunnel active: ${webhookUrl}`)
  }

  // Set webhook URL on LINE
  try {
    await lineClient.setWebhookUrl(webhookUrl)
    console.error(`[line] Webhook URL set on LINE: ${webhookUrl}`)
  } catch (err: any) {
    console.error(`[line] WARNING: Failed to set webhook URL: ${err.message}`)
    console.error('[line] Set it manually in the LINE Developer Console.')
  }

  // Test webhook
  const ok = await lineClient.testWebhook()
  if (ok) {
    console.error('[line] Webhook test passed ✓')
  } else {
    console.error('[line] WARNING: Webhook test failed. LINE may not be able to reach the webhook.')
  }

  console.error('[line] Ready — waiting for messages')

  // --- Cleanup on exit ---

  process.on('SIGINT', () => {
    stopTunnel()
    server.stop()
    process.exit(0)
  })

  process.on('SIGTERM', () => {
    stopTunnel()
    server.stop()
    process.exit(0)
  })

}

main().catch((err) => {
  console.error('[line] Fatal error:', err)
  process.exit(1)
})
```

- [ ] **Step 2: Verify the project compiles**

```bash
cd plugins/line && bun build server.ts --outdir /tmp/line-plugin-check --target bun 2>&1 | head -5
```

Expected: No TypeScript errors.

- [ ] **Step 3: Run all tests**

```bash
cd plugins/line && bun test
```

Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add plugins/line/server.ts
git commit -m "feat(line-plugin): MCP server with tools, access control, inbound handling"
```

---

## Task 8: Skills & Plugin Docs

**Files:**
- Create: `plugins/line/skills/access/SKILL.md`
- Create: `plugins/line/skills/configure/SKILL.md`
- Create: `plugins/line/README.md`
- Create: `plugins/line/ACCESS.md`
- Create: `plugins/line/LICENSE`

- [ ] **Step 1: Create access skill**

```markdown
<!-- skills/access/SKILL.md -->
---
name: access
description: Manage LINE channel access control — pair users, allow/deny, list
---

## Commands

### `/line:access pair <CODE>`
Approve a pairing request. The code is shown to users who message the bot for the first time.

### `/line:access allow <ID>`
Add a user ID or group ID to the allowlist. Groups default to requireMention: true.
- User IDs start with `U` (e.g., `U1234abcd...`)
- Group IDs start with `C` (e.g., `C9876efgh...`)

### `/line:access deny <ID>`
Remove a user or disable a group.

### `/line:access list`
Show current allowlist, enabled groups, and pending pairing codes.

## Notes

Access state is stored in `~/.claude/channels/line/access.json`.
```

- [ ] **Step 2: Create configure skill**

```markdown
<!-- skills/configure/SKILL.md -->
---
name: configure
description: Configure LINE channel plugin — set tokens, tunnel URL
---

## Commands

### `/line:configure token`
Set LINE channel credentials. You need:
1. **Channel Secret** — from LINE Developer Console → Channel settings → Basic settings
2. **Channel Access Token** — from LINE Developer Console → Messaging API → Channel access token (long-lived)

Credentials are stored in `~/.claude/channels/line/.env` (chmod 600).

### `/line:configure tunnel <URL>`
Set a custom tunnel URL instead of the auto-generated cloudflared tunnel.
Useful if you have your own domain or use ngrok.
```

- [ ] **Step 3: Create README.md**

Write a setup guide covering:
- Prerequisites (bun, cloudflared)
- Quick start (`claude --channels plugin:line`)
- First-time setup (`/line:configure token`)
- Access control overview
- Tunnel options (default, `--tunnel-url`, `--no-tunnel`)
- Environment variable configuration for Docker

- [ ] **Step 4: Create ACCESS.md**

Document the full access control model:
- DM policies (pairing, allowlist, disabled)
- Group filtering (requireMention, triggerPrefix)
- Pairing flow with examples
- access.json format

- [ ] **Step 5: Create LICENSE (Apache 2.0)**

```bash
cd plugins/line && curl -sL https://www.apache.org/licenses/LICENSE-2.0.txt > LICENSE
```

- [ ] **Step 6: Commit**

```bash
git add plugins/line/skills/ plugins/line/README.md plugins/line/ACCESS.md plugins/line/LICENSE
git commit -m "docs(line-plugin): skills, README, ACCESS guide, LICENSE"
```

---

## Task 9: Local Integration Test

**Files:**
- Create: `plugins/line/__tests__/integration.test.ts`

End-to-end test: start the HTTP server, send a mocked LINE webhook, verify the gate logic and notification flow.

- [ ] **Step 1: Write integration test**

```typescript
// __tests__/integration.test.ts
import { describe, it, expect, afterEach } from 'bun:test'
import { createHmac } from 'crypto'

const TEST_SECRET = 'test-secret'
const TEST_PORT = 19999

function sign(body: string): string {
  return createHmac('sha256', TEST_SECRET).update(body).digest('base64')
}

describe('Webhook HTTP Integration', () => {
  let server: ReturnType<typeof Bun.serve> | null = null

  afterEach(() => {
    if (server) server.stop()
    server = null
  })

  it('returns 200 on valid webhook with text message', async () => {
    const messages: any[] = []

    // Import and start server
    const { startHttpServer } = await import('../line')
    const result = startHttpServer(
      {
        channelSecret: TEST_SECRET,
        channelAccessToken: 'dummy',
        port: TEST_PORT,
        noTunnel: true,
        inboxDir: '/tmp/test-inbox',
      },
      {
        onMessage: (msg) => messages.push(msg),
        onFollow: () => {},
        onJoin: () => {},
        onLeave: () => {},
      }
    )
    server = result.server

    const body = JSON.stringify({
      events: [
        {
          type: 'message',
          message: { type: 'text', id: 'msg1', text: 'hello' },
          source: { type: 'user', userId: 'U123' },
          replyToken: 'token123',
          timestamp: Date.now(),
        },
      ],
    })

    const res = await fetch(`http://localhost:${TEST_PORT}/webhook`, {
      method: 'POST',
      body,
      headers: {
        'content-type': 'application/json',
        'x-line-signature': sign(body),
      },
    })

    expect(res.status).toBe(200)
    // Give async handler time to process
    await Bun.sleep(50)
    expect(messages.length).toBe(1)
    expect(messages[0].text).toBe('hello')
    expect(messages[0].chatId).toBe('U123')
    expect(messages[0].replyToken).toBe('token123')
  })

  it('returns 200 but ignores invalid signature', async () => {
    const messages: any[] = []

    const { startHttpServer } = await import('../line')
    const result = startHttpServer(
      {
        channelSecret: TEST_SECRET,
        channelAccessToken: 'dummy',
        port: TEST_PORT + 1,
        noTunnel: true,
        inboxDir: '/tmp/test-inbox',
      },
      {
        onMessage: (msg) => messages.push(msg),
        onFollow: () => {},
        onJoin: () => {},
        onLeave: () => {},
      }
    )
    server = result.server

    const body = JSON.stringify({ events: [{ type: 'message' }] })
    const res = await fetch(`http://localhost:${TEST_PORT + 1}/webhook`, {
      method: 'POST',
      body,
      headers: {
        'content-type': 'application/json',
        'x-line-signature': 'bad-signature',
      },
    })

    expect(res.status).toBe(200)
    await Bun.sleep(50)
    expect(messages.length).toBe(0) // Not forwarded
  })

  it('returns health check', async () => {
    const { startHttpServer } = await import('../line')
    const result = startHttpServer(
      {
        channelSecret: TEST_SECRET,
        channelAccessToken: 'dummy',
        port: TEST_PORT + 2,
        noTunnel: true,
        inboxDir: '/tmp/test-inbox',
      },
      {
        onMessage: () => {},
        onFollow: () => {},
        onJoin: () => {},
        onLeave: () => {},
      }
    )
    server = result.server

    const res = await fetch(`http://localhost:${TEST_PORT + 2}/health`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.status).toBe('ok')
  })
})
```

- [ ] **Step 2: Run integration test**

```bash
cd plugins/line && bun test __tests__/integration.test.ts
```

Expected: All PASS.

- [ ] **Step 3: Run full test suite**

```bash
cd plugins/line && bun test
```

Expected: All tests PASS across all test files.

- [ ] **Step 4: Commit**

```bash
git add plugins/line/__tests__/integration.test.ts
git commit -m "test(line-plugin): integration tests for webhook HTTP handling"
```

---

## Task 10: Manual Smoke Test

No code changes. Verify the plugin works end-to-end with a real LINE bot.

- [ ] **Step 1: Set up LINE credentials**

```bash
mkdir -p ~/.claude/channels/line
cat > ~/.claude/channels/line/.env << 'EOF'
LINE_CHANNEL_SECRET=<your-secret>
LINE_CHANNEL_ACCESS_TOKEN=<your-token>
EOF
chmod 600 ~/.claude/channels/line/.env
```

- [ ] **Step 2: Start the plugin directly (no Claude Code)**

```bash
cd plugins/line && bun server.ts --no-tunnel --port 3000
```

Expected: Server starts, prints "No tunnel" and "Ready".

- [ ] **Step 3: Test webhook locally**

```bash
# In another terminal, send a test webhook
SECRET=<your-secret>
BODY='{"events":[{"type":"message","message":{"type":"text","id":"test1","text":"hello"},"source":{"type":"user","userId":"Utest"},"replyToken":"dummy","timestamp":1234567890000}]}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -binary | base64)
curl -X POST http://localhost:3000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY"
```

Expected: Returns "OK", server logs show the message was received.

- [ ] **Step 4: Test with cloudflared tunnel**

```bash
cd plugins/line && bun server.ts
```

Expected: Tunnel starts, webhook URL is set on LINE, "Webhook test passed" logged.

- [ ] **Step 5: Send a real LINE message to the bot**

Send "hello" from LINE app. Expected: Server logs show the message. (No Claude Code connected, so no response — but the inbound pipeline works.)

- [ ] **Step 6: Final commit with any fixes**

```bash
git add -A plugins/line/
git commit -m "fix(line-plugin): smoke test fixes"
```
