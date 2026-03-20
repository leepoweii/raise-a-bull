import { describe, it, expect } from 'bun:test'
import { chunkMessage } from '../chunking'

describe('chunkMessage', () => {
  it('returns single chunk for short messages', () => {
    const chunks = chunkMessage('hello', 5000)
    expect(chunks).toEqual(['hello'])
  })
  it('splits on paragraph boundaries', () => {
    const text = 'paragraph one\n\nparagraph two\n\nparagraph three'
    const chunks = chunkMessage(text, 30)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) { expect(chunk.length).toBeLessThanOrEqual(30) }
  })
  it('splits on newline if no paragraph break fits', () => {
    const text = 'line one\nline two\nline three\nline four'
    const chunks = chunkMessage(text, 20)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) { expect(chunk.length).toBeLessThanOrEqual(20) }
  })
  it('hard splits if no break point found', () => {
    const text = 'a'.repeat(100)
    const chunks = chunkMessage(text, 30)
    expect(chunks.length).toBe(4)
    for (const chunk of chunks) { expect(chunk.length).toBeLessThanOrEqual(30) }
  })
  it('handles empty string', () => {
    expect(chunkMessage('', 5000)).toEqual([''])
  })
  it('defaults to LINE 5000 char limit', () => {
    const text = 'a'.repeat(10000)
    const chunks = chunkMessage(text)
    expect(chunks.length).toBe(2)
    expect(chunks[0].length).toBe(5000)
    expect(chunks[1].length).toBe(5000)
  })
})
