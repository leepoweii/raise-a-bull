import { readFileSync, writeFileSync, existsSync } from 'fs'
import { randomBytes } from 'crypto'

export interface GroupConfig {
  enabled: boolean
  requireMention: boolean
  triggerPrefix?: string
  mode?: 'filtered' | 'observer'
  autoFlush?: 'discard' | 'forward'
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

export function isAllowedChat(config: AccessConfig, chatId: string): boolean {
  return isUserAllowed(config, chatId) || isGroupEnabled(config, chatId)
}

export function isGroupEnabled(config: AccessConfig, groupId: string): boolean {
  return config.groups[groupId]?.enabled === true
}

export function getGroupConfig(config: AccessConfig, groupId: string): GroupConfig | undefined {
  return config.groups[groupId]
}

export function createPairingCode(config: AccessConfig, userId: string): string {
  const code = randomBytes(3).toString('hex')
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
  if (id.startsWith('C') || id.startsWith('R')) {
    if (config.groups[id]) {
      config.groups[id].enabled = true
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

export interface FilterResult {
  forward: boolean
  buffer?: boolean
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

  const isObserver = group.mode === 'observer'

  // triggerPrefix takes priority over requireMention
  if (group.triggerPrefix) {
    if (text.startsWith(group.triggerPrefix)) {
      return { forward: true, text: text.slice(group.triggerPrefix.length).trim() }
    }
    return isObserver ? { forward: false, buffer: true } : { forward: false }
  }

  // requireMention (default true)
  if (group.requireMention !== false) {
    if (isMention) return { forward: true, text }
    return isObserver ? { forward: false, buffer: true } : { forward: false }
  }

  // requireMention: false, no prefix — forward all
  return { forward: true, text }
}
