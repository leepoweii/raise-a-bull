import { describe, it, expect } from 'bun:test'
import { MessageBuffer, type BufferedMessage } from '../message-buffer'

function makeMsg(overrides: Partial<BufferedMessage> = {}): BufferedMessage {
  return {
    userId: 'U123',
    displayName: 'Alice',
    text: 'hello',
    messageType: 'text',
    timestamp: '2026-03-21T14:00:00.000Z',
    pushedAt: Date.now(),
    ...overrides,
  }
}

describe('MessageBuffer', () => {
  describe('push and flush', () => {
    it('push adds message and flush returns them in order', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ text: 'first' }))
      buf.push('C1', makeMsg({ text: 'second' }))
      const msgs = buf.flush('C1')
      expect(msgs).toHaveLength(2)
      expect(msgs[0].text).toBe('first')
      expect(msgs[1].text).toBe('second')
    })

    it('flush clears the buffer', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg())
      buf.flush('C1')
      expect(buf.flush('C1')).toHaveLength(0)
    })

    it('flush on unknown group returns empty array', () => {
      const buf = new MessageBuffer()
      expect(buf.flush('C999')).toHaveLength(0)
    })

    it('multiple groups buffer independently', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ text: 'group1' }))
      buf.push('C2', makeMsg({ text: 'group2' }))
      expect(buf.flush('C1')).toHaveLength(1)
      expect(buf.flush('C2')).toHaveLength(1)
    })
  })

  describe('buffer cap', () => {
    it('discard mode: drops oldest when cap exceeded', () => {
      const buf = new MessageBuffer(3)
      buf.push('C1', makeMsg({ text: 'a' }), () => 'discard')
      buf.push('C1', makeMsg({ text: 'b' }), () => 'discard')
      buf.push('C1', makeMsg({ text: 'c' }), () => 'discard')
      buf.push('C1', makeMsg({ text: 'd' }), () => 'discard')
      const msgs = buf.flush('C1')
      expect(msgs).toHaveLength(3)
      expect(msgs[0].text).toBe('b')
      expect(msgs[2].text).toBe('d')
    })

    it('forward mode: flushes all when cap exceeded and returns them', () => {
      const buf = new MessageBuffer(3)
      const flushed: BufferedMessage[] = []
      const onCapFlush = (groupId: string, msgs: BufferedMessage[]) => {
        flushed.push(...msgs)
      }
      buf.push('C1', makeMsg({ text: 'a' }), () => 'forward', onCapFlush)
      buf.push('C1', makeMsg({ text: 'b' }), () => 'forward', onCapFlush)
      buf.push('C1', makeMsg({ text: 'c' }), () => 'forward', onCapFlush)
      buf.push('C1', makeMsg({ text: 'd' }), () => 'forward', onCapFlush)
      expect(flushed).toHaveLength(3)
      expect(flushed[0].text).toBe('a')
      // Buffer now has only 'd'
      expect(buf.flush('C1')).toHaveLength(1)
    })
  })

  describe('cleanup', () => {
    it('discard: drops expired messages silently', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ pushedAt: Date.now() - 3700_000 }))
      buf.push('C1', makeMsg({ pushedAt: Date.now(), text: 'fresh' }))
      const forwarded = buf.cleanup(() => 'discard')
      expect(forwarded.size).toBe(0)
      const remaining = buf.flush('C1')
      expect(remaining).toHaveLength(1)
      expect(remaining[0].text).toBe('fresh')
    })

    it('forward: returns expired messages for notification', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ pushedAt: Date.now() - 3700_000, text: 'old' }))
      buf.push('C1', makeMsg({ pushedAt: Date.now(), text: 'fresh' }))
      const forwarded = buf.cleanup(() => 'forward')
      expect(forwarded.size).toBe(1)
      expect(forwarded.get('C1')!).toHaveLength(1)
      expect(forwarded.get('C1')![0].text).toBe('old')
      expect(buf.flush('C1')).toHaveLength(1)
    })

    it('messages within TTL are not cleaned up', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ pushedAt: Date.now() }))
      const forwarded = buf.cleanup(() => 'forward')
      expect(forwarded.size).toBe(0)
      expect(buf.flush('C1')).toHaveLength(1)
    })

    it('cleans up multiple groups independently', () => {
      const buf = new MessageBuffer()
      buf.push('C1', makeMsg({ pushedAt: Date.now() - 3700_000, text: 'old1' }))
      buf.push('C2', makeMsg({ pushedAt: Date.now() - 3700_000, text: 'old2' }))
      const forwarded = buf.cleanup((gid) => gid === 'C1' ? 'forward' : 'discard')
      expect(forwarded.size).toBe(1)
      expect(forwarded.has('C1')).toBe(true)
      expect(forwarded.has('C2')).toBe(false)
    })
  })
})
