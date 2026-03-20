import { describe, it, expect, afterEach } from 'bun:test'
import { createHmac } from 'crypto'

const TEST_SECRET = 'test-secret'

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

    const { startHttpServer } = await import('../line')
    const result = startHttpServer(
      {
        channelSecret: TEST_SECRET,
        channelAccessToken: 'dummy',
        port: 19999,
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

    const res = await fetch('http://localhost:19999/webhook', {
      method: 'POST',
      body,
      headers: {
        'content-type': 'application/json',
        'x-line-signature': sign(body),
      },
    })

    expect(res.status).toBe(200)
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
        port: 20000,
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
    const res = await fetch('http://localhost:20000/webhook', {
      method: 'POST',
      body,
      headers: {
        'content-type': 'application/json',
        'x-line-signature': 'bad-signature',
      },
    })

    expect(res.status).toBe(200)
    await Bun.sleep(50)
    expect(messages.length).toBe(0)
  })

  it('returns health check', async () => {
    const { startHttpServer } = await import('../line')
    const result = startHttpServer(
      {
        channelSecret: TEST_SECRET,
        channelAccessToken: 'dummy',
        port: 20001,
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

    const res = await fetch('http://localhost:20001/health')
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.status).toBe('ok')
  })
})
