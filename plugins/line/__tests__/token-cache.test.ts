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
    cache.set('old', 'Uabc', 'oldtoken')
    cache['entries'].get('old')!.timestamp = Date.now() - 120_000
    cache.set('new', 'Uabc', 'newtoken')
    cache.cleanup()
    expect(cache.get('old')).toBeUndefined()
    expect(cache.get('new')).toBeDefined()
  })
})
