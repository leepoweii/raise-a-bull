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

  // --- Observer mode tests ---

  it('observer: buffers non-mention when requireMention is true', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(false)
    expect(result.buffer).toBe(true)
  })

  it('observer: forwards mention when requireMention is true', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', true)
    expect(result.forward).toBe(true)
    expect(result.text).toBe('hello')
  })

  it('observer: buffers non-matching prefix (even if mention)', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, triggerPrefix: 'CC', mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', true)
    expect(result.forward).toBe(false)
    expect(result.buffer).toBe(true)
  })

  it('observer: forwards matching prefix and strips it', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, triggerPrefix: 'CC', mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'CC help me', false)
    expect(result.forward).toBe(true)
    expect(result.text).toBe('help me')
  })

  it('observer: forwards all when no trigger mechanism set', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: false, mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(true)
    expect(result.text).toBe('hello')
  })

  it('observer: buffers non-mention when requireMention true and no prefix', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true, mode: 'observer' }
    const result = shouldForwardGroupMessage(config, 'C123', 'random chat', false)
    expect(result.forward).toBe(false)
    expect(result.buffer).toBe(true)
  })

  it('filtered mode: no buffer field on rejected messages', () => {
    const config = defaultAccess()
    config.groups['C123'] = { enabled: true, requireMention: true }
    const result = shouldForwardGroupMessage(config, 'C123', 'hello', false)
    expect(result.forward).toBe(false)
    expect(result.buffer).toBeUndefined()
  })
})
