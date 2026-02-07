import { decoder } from './encoding'

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

export async function* eventStreamToMessages(events: AsyncGenerator<string>): AsyncGenerator<string, void, void> {
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

export function readerToMessages(reader: ReadableStreamDefaultReader<Uint8Array>) {
  return eventStreamToMessages(readerToEventStream(reader))
}
