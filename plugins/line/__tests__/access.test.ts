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
