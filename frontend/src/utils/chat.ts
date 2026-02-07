import { useStorage } from '@vueuse/core'
import API from '@/api/core'

interface Message {
  role: 'system' | 'user' | 'assistant'
  content: string
  generating?: boolean
}

export const HISTORY = useStorage<Message[]>('history', [])

declare global {
  interface WindowEventMap {
    token: CustomEvent<string>
  }
}

export function chatStream(content: string) {
  HISTORY.value.push({ role: 'user', content })

  API.chatStream(content).then(async ({ response }) => {
    HISTORY.value.push({ role: 'assistant', content: '', generating: true })
    const message = HISTORY.value[HISTORY.value.length - 1]!

    for await (const token of response) {
      message.content += token
      window.dispatchEvent(new CustomEvent('token', { detail: token }))
    }

    delete message.generating
  }).catch((err) => {
    HISTORY.value.push({ role: 'system', content: `Error: ${err.message}` })
  })
}
