import { validateSignature, messagingApi, type WebhookEvent, type MessageEvent } from '@line/bot-sdk'
import { TokenCache } from './token-cache'
import { chunkMessage } from './chunking'

const { MessagingApiClient, MessagingApiBlobClient } = messagingApi

export interface LineConfig {
  channelSecret: string
  channelAccessToken: string
  port: number
  tunnelUrl?: string
  noTunnel?: boolean
  inboxDir: string
}

export interface InboundMessage {
  chatId: string
  messageId: string
  userId: string
  text: string
  messageType: string
  replyToken?: string
  timestamp: string
  mentionedUserIds?: string[]
}

export interface LineCallbacks {
  onMessage: (msg: InboundMessage) => void | Promise<void>
  onFollow: (userId: string) => void
  onJoin: (groupId: string) => void
  onLeave: (groupId: string) => void
}

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
        this.tokenCache.consume(replyTo)
      }
    }
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
    await this.client.setWebhookEndpoint({ endpoint: url })
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
                const mentionedUserIds = msgEvent.message.type === 'text'
                  && (msgEvent.message as any).mention?.mentionees
                  ? (msgEvent.message as any).mention.mentionees.map((m: any) => m.userId).filter(Boolean)
                  : undefined
                Promise.resolve(callbacks.onMessage({
                  chatId: ids.chatId,
                  messageId: msgEvent.message.id,
                  userId: ids.userId,
                  text: content,
                  messageType: msgEvent.message.type,
                  replyToken: event.replyToken,
                  timestamp: new Date(event.timestamp).toISOString(),
                  mentionedUserIds,
                })).catch((err) => console.error('[line] Error handling message:', err))
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
