const LINE_MAX_LENGTH = 5000

export function chunkMessage(text: string, maxLength = LINE_MAX_LENGTH): string[] {
  if (text.length <= maxLength) return [text]
  const chunks: string[] = []
  let remaining = text
  while (remaining.length > 0) {
    if (remaining.length <= maxLength) { chunks.push(remaining); break }
    let splitAt = -1
    const window = remaining.slice(0, maxLength)
    const paraBreak = window.lastIndexOf('\n\n')
    if (paraBreak > 0) splitAt = paraBreak
    if (splitAt === -1) { const newline = window.lastIndexOf('\n'); if (newline > 0) splitAt = newline }
    if (splitAt === -1) splitAt = maxLength
    chunks.push(remaining.slice(0, splitAt))
    remaining = remaining.slice(splitAt).replace(/^\n+/, '')
  }
  return chunks
}
