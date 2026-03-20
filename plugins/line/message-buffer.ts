export const OBSERVER_BUFFER_TTL_MS = 60 * 60 * 1000  // 60 minutes
export const DEFAULT_MAX_BUFFER = 200

export interface BufferedMessage {
  userId: string
  displayName: string
  text: string
  messageType: string
  timestamp: string
  pushedAt: number
}

export class MessageBuffer {
  private buffers = new Map<string, BufferedMessage[]>()
  private maxPerGroup: number

  constructor(maxPerGroup = DEFAULT_MAX_BUFFER) {
    this.maxPerGroup = maxPerGroup
  }

  push(
    groupId: string,
    msg: BufferedMessage,
    getAutoFlush?: () => 'discard' | 'forward',
    onCapFlush?: (groupId: string, msgs: BufferedMessage[]) => void,
  ): void {
    let buf = this.buffers.get(groupId)
    if (!buf) {
      buf = []
      this.buffers.set(groupId, buf)
    }

    if (buf.length >= this.maxPerGroup) {
      const mode = getAutoFlush?.() ?? 'forward'
      if (mode === 'forward' && onCapFlush) {
        onCapFlush(groupId, [...buf])
        buf.length = 0
      } else {
        buf.shift()
      }
    }

    buf.push(msg)
  }

  flush(groupId: string): BufferedMessage[] {
    const buf = this.buffers.get(groupId)
    if (!buf || buf.length === 0) return []
    const msgs = [...buf]
    buf.length = 0
    return msgs
  }

  cleanup(
    getAutoFlush: (groupId: string) => 'discard' | 'forward',
  ): Map<string, BufferedMessage[]> {
    const now = Date.now()
    const toForward = new Map<string, BufferedMessage[]>()

    for (const [groupId, buf] of this.buffers) {
      const expired: BufferedMessage[] = []
      const kept: BufferedMessage[] = []

      for (const msg of buf) {
        if (now - msg.pushedAt > OBSERVER_BUFFER_TTL_MS) {
          expired.push(msg)
        } else {
          kept.push(msg)
        }
      }

      if (expired.length > 0) {
        const mode = getAutoFlush(groupId)
        if (mode === 'forward') {
          toForward.set(groupId, expired)
        }
      }

      if (kept.length === 0) {
        this.buffers.delete(groupId)
      } else {
        this.buffers.set(groupId, kept)
      }
    }

    return toForward
  }
}
