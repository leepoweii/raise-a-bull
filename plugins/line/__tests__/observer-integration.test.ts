import { describe, it, expect } from 'bun:test'
import { MessageBuffer } from '../message-buffer'
import { defaultAccess } from '../access'
import { createHandleInbound, type HandleInboundDeps } from '../server'
import type { InboundMessage } from '../line'

function makeStubLineClient() {
  return {
    getProfile: async (userId: string) => ({ displayName: `User_${userId}`, pictureUrl: undefined }),
    pushMessage: async () => {},
    cacheReplyToken: () => {},
    showLoading: async () => {},
  } as any
}

function makeDeps(overrides: Partial<HandleInboundDeps> = {}) {
  const notifications: any[] = []
  const profileCache = new Map<string, { name: string; fetchedAt: number }>()
  const access = defaultAccess()
  return {
    lineClient: makeStubLineClient(),
    messageBuffer: new MessageBuffer(),
    getAccess: () => access,
    persistAccess: () => {},
    notifyFn: (params: any) => notifications.push(params),
    botUserId: 'BOT_ID',
    getCachedProfile: (userId: string) => {
      const e = profileCache.get(userId)
      return e && Date.now() - e.fetchedAt < 3600_000 ? e.name : undefined
    },
    setCachedProfile: (userId: string, name: string) => {
      profileCache.set(userId, { name, fetchedAt: Date.now() })
    },
    notifications,
    access,
    ...overrides,
  }
}

function makeMsg(overrides: Partial<InboundMessage> = {}): InboundMessage {
  return {
    chatId: 'C123',
    messageId: `msg_${Date.now()}_${Math.random()}`,
    userId: 'U456',
    text: 'hello',
    messageType: 'text',
    replyToken: 'token_test',
    timestamp: new Date().toISOString(),
    ...overrides,
  }
}

describe('Observer Mode Integration', () => {
  it('buffers non-trigger messages, flushes on trigger with <context> block', async () => {
    const state = makeDeps()
    // Set up observer mode group
    state.access.groups['C123'] = {
      enabled: true,
      requireMention: true,
      mode: 'observer',
    }

    const handleInbound = createHandleInbound(state)

    // Send 3 non-mention messages (these should be buffered)
    await handleInbound(makeMsg({ text: 'msg one', userId: 'U001', mentionedUserIds: [] }))
    await handleInbound(makeMsg({ text: 'msg two', userId: 'U002', mentionedUserIds: [] }))
    await handleInbound(makeMsg({ text: 'msg three', userId: 'U003', mentionedUserIds: [] }))

    // No notifications yet
    expect(state.notifications.length).toBe(0)

    // Send mention (trigger)
    const triggerMsgId = `trigger_${Date.now()}`
    await handleInbound(makeMsg({
      text: 'hey BOT_ID what do you think?',
      userId: 'U456',
      messageId: triggerMsgId,
      mentionedUserIds: ['BOT_ID'],
    }))

    // Should have exactly 1 notification
    expect(state.notifications.length).toBe(1)

    const notification = state.notifications[0]
    // Should contain context block
    expect(notification.content).toContain('<context')
    // Should contain all 3 buffered texts
    expect(notification.content).toContain('msg one')
    expect(notification.content).toContain('msg two')
    expect(notification.content).toContain('msg three')
    // Should contain the trigger text
    expect(notification.content).toContain('hey BOT_ID what do you think?')
    // meta.message_id should match the trigger message
    expect(notification.meta.message_id).toBe(triggerMsgId)
  })

  it('trigger with empty buffer sends without <context> block', async () => {
    const state = makeDeps()
    state.access.groups['C123'] = {
      enabled: true,
      requireMention: true,
      mode: 'observer',
    }

    const handleInbound = createHandleInbound(state)

    // Send 1 mention message with no prior buffered messages
    const triggerMsgId = `trigger_empty_${Date.now()}`
    await handleInbound(makeMsg({
      text: 'hello bot',
      userId: 'U456',
      messageId: triggerMsgId,
      mentionedUserIds: ['BOT_ID'],
    }))

    expect(state.notifications.length).toBe(1)
    const notification = state.notifications[0]
    // Should NOT contain a context block
    expect(notification.content).not.toContain('<context')
    // Should contain the trigger text
    expect(notification.content).toContain('hello bot')
  })

  it('auto-flush forward: cleanup returns expired messages', () => {
    const buffer = new MessageBuffer()
    const groupId = 'C_AUTOFLUSH'
    const farPast = Date.now() - 2 * 60 * 60 * 1000 // 2 hours ago (past TTL)

    // Push 3 expired messages directly
    buffer.push(groupId, {
      userId: 'U1',
      displayName: 'Alice',
      text: 'expired msg 1',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })
    buffer.push(groupId, {
      userId: 'U2',
      displayName: 'Bob',
      text: 'expired msg 2',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })
    buffer.push(groupId, {
      userId: 'U3',
      displayName: 'Charlie',
      text: 'expired msg 3',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })

    // Cleanup with 'forward' mode
    const toForward = buffer.cleanup(() => 'forward')

    // Returned map should have the expired messages for this group
    expect(toForward.has(groupId)).toBe(true)
    const msgs = toForward.get(groupId)!
    expect(msgs.length).toBe(3)
    expect(msgs[0].text).toBe('expired msg 1')
    expect(msgs[1].text).toBe('expired msg 2')
    expect(msgs[2].text).toBe('expired msg 3')
  })

  it('auto-flush discard: cleanup drops expired messages', () => {
    const buffer = new MessageBuffer()
    const groupId = 'C_DISCARD'
    const farPast = Date.now() - 2 * 60 * 60 * 1000 // 2 hours ago (past TTL)

    // Push 3 expired messages
    buffer.push(groupId, {
      userId: 'U1',
      displayName: 'Alice',
      text: 'expired msg 1',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })
    buffer.push(groupId, {
      userId: 'U2',
      displayName: 'Bob',
      text: 'expired msg 2',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })
    buffer.push(groupId, {
      userId: 'U3',
      displayName: 'Charlie',
      text: 'expired msg 3',
      messageType: 'text',
      timestamp: new Date(farPast).toISOString(),
      pushedAt: farPast,
    })

    // Cleanup with 'discard' mode
    const toForward = buffer.cleanup(() => 'discard')

    // Returned map should be empty (discarded, not forwarded)
    expect(toForward.size).toBe(0)
    // Buffer for this group should be empty
    const remaining = buffer.flush(groupId)
    expect(remaining.length).toBe(0)
  })

  it('filtered mode: drops non-mention, forwards mention immediately', async () => {
    const state = makeDeps()
    // Default filtered mode (no mode specified = 'filtered' behavior)
    state.access.groups['C123'] = {
      enabled: true,
      requireMention: true,
      // mode not set = filtered
    }

    const handleInbound = createHandleInbound(state)

    // Send non-mention message — should be dropped (no notification)
    await handleInbound(makeMsg({
      text: 'just chatting',
      userId: 'U001',
      mentionedUserIds: [],
    }))

    expect(state.notifications.length).toBe(0)

    // Send mention — should be forwarded immediately without <context> block
    const triggerMsgId = `filtered_trigger_${Date.now()}`
    await handleInbound(makeMsg({
      text: 'hey bot help me',
      userId: 'U456',
      messageId: triggerMsgId,
      mentionedUserIds: ['BOT_ID'],
    }))

    expect(state.notifications.length).toBe(1)
    const notification = state.notifications[0]
    // Filtered mode does NOT produce a context block
    expect(notification.content).not.toContain('<context')
    expect(notification.content).toContain('hey bot help me')
  })
})
