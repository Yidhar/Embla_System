export const decoder = new TextDecoder('utf-8')

export interface StreamChunk {
  type:
    | 'content'
    | 'reasoning'
    | 'content_clean'
    | 'round_start'
    | 'tool_calls'
    | 'tool_results'
    | 'round_end'
    | 'tool_stage'
    | 'auth_expired'
  text?: string
  round?: number
  calls?: Array<{ agentType: string, service_name?: string, tool_name?: string, message?: string }>
  results?: Array<{ service_name: string, tool_name?: string, result: string, status: string }>
  phase?: 'plan' | 'execute' | 'verify' | 'repair'
  status?: 'start' | 'success' | 'error' | 'skip'
  reason?: string
  decision?: string
  actionable_calls?: number
  success_count?: number
  error_count?: number
  validation_errors?: number
  live2d_calls?: number
  consecutive_no_tool_rounds?: number
  consecutive_tool_failures?: number
  consecutive_validation_failures?: number
  threshold?: number
  pending_tool_intent?: boolean
  summary?: boolean
  has_more?: boolean
}

export function decodeBase64(base64: string) {
  const binaryString = atob(base64)
  const bytes = new Uint8Array(binaryString.length)

  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i)
  }

  return decoder.decode(bytes)
}

export function decodeStreamChunk(base64: string): StreamChunk {
  const decoded = decodeBase64(base64)
  try {
    const parsed = JSON.parse(decoded)
    if (parsed && typeof parsed === 'object' && 'type' in parsed) {
      return parsed as StreamChunk
    }
  }
  catch {
    // Fallback for old format (plain text)
  }
  return { type: 'content', text: decoded }
}

export async function* readerToEventStream(reader: ReadableStreamDefaultReader<Uint8Array>): AsyncGenerator<string, void, void> {
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()

      if (done) {
        if (buffer) {
          const events = buffer.split('\n\n')
          for (const event of events.filter(e => e.trim() !== '')) {
            yield event
          }
        }
        return
      }

      buffer += decoder.decode(value, { stream: !done })

      const events = buffer.split('\n\n')
      buffer = events.pop() || ''

      for (const event of events) {
        if (event.trim()) {
          yield event
        }
      }
    }
  }
  finally {
    reader.releaseLock()
  }
}

export async function* eventStreamToMessageStream(events: AsyncGenerator<string>): AsyncGenerator<string, void, void> {
  for await (const event of events) {
    if (event.startsWith('data: ')) {
      const data = event.slice(6)
      if (data === '[DONE]') {
        return
      }
      yield data
    }
  }
}

export function readerToMessageStream(reader: ReadableStreamDefaultReader<Uint8Array>) {
  return eventStreamToMessageStream(readerToEventStream(reader))
}
