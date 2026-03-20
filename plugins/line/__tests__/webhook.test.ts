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
    const event = { type: 'message', message: { type: 'text', id: 'msg1', text: 'hello world' } }
    expect(formatInboundContent(event as any)).toBe('hello world')
  })
  it('formats sticker message', () => {
    const event = { type: 'message', message: { type: 'sticker', id: 'msg2', packageId: '1', stickerId: '2' } }
    expect(formatInboundContent(event as any)).toBe('(sticker: package=1, id=2)')
  })
  it('formats location message', () => {
    const event = { type: 'message', message: { type: 'location', id: 'msg3', title: 'Tokyo Tower', address: 'Minato, Tokyo', latitude: 35.6586, longitude: 139.7454 } }
    const content = formatInboundContent(event as any)
    expect(content).toContain('Tokyo Tower')
    expect(content).toContain('35.6586')
  })
  it('formats image with external provider', () => {
    const event = { type: 'message', message: { type: 'image', id: 'msg4', contentProvider: { type: 'external', originalContentUrl: 'https://example.com/img.jpg' } } }
    expect(formatInboundContent(event as any)).toContain('https://example.com/img.jpg')
  })
  it('formats image with line provider as pending download', () => {
    const event = { type: 'message', message: { type: 'image', id: 'msg5', contentProvider: { type: 'line' } } }
    expect(formatInboundContent(event as any)).toContain('msg5')
  })
})
