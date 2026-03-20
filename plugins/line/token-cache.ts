interface CacheEntry {
  chatId: string
  replyToken: string
  timestamp: number
}

const TOKEN_TTL_MS = 60_000

export class TokenCache {
  private entries = new Map<string, CacheEntry>()

  set(messageId: string, chatId: string, replyToken: string): void {
    this.entries.set(messageId, { chatId, replyToken, timestamp: Date.now() })
  }

  get(messageId: string): { chatId: string; replyToken: string } | undefined {
    const entry = this.entries.get(messageId)
    if (!entry) return undefined
    return { chatId: entry.chatId, replyToken: entry.replyToken }
  }

  consume(messageId: string): void {
    this.entries.delete(messageId)
  }

  cleanup(): void {
    const now = Date.now()
    for (const [id, entry] of this.entries) {
      if (now - entry.timestamp > TOKEN_TTL_MS) {
        this.entries.delete(id)
      }
    }
  }
}
