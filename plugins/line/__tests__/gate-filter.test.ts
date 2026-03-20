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
})
