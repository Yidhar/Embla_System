import type { StreamChunk } from '@/utils/encoding'
import { useStorage } from '@vueuse/core'
import { ref } from 'vue'
import API from '@/api/core'

export interface Message {
  role: 'system' | 'user' | 'assistant'
  content: string
  reasoning?: string
  generating?: boolean
  sender?: string
}

export const CURRENT_SESSION_ID = useStorage<string | null>('naga-session', null)
export const MESSAGES = ref<Message[]>([])

export async function loadCurrentSession() {
  if (CURRENT_SESSION_ID.value) {
    try {
      const detail = await API.getSessionDetail(CURRENT_SESSION_ID.value)
      MESSAGES.value = detail.messages.map(m => ({
        role: m.role as Message['role'],
        content: m.content,
      }))
      return
    }
    catch {
      CURRENT_SESSION_ID.value = null
    }
  }
  // No session — load persistent context history
  try {
    const ctx = await API.loadContext()
    if (ctx.messages?.length) {
      MESSAGES.value = ctx.messages.map((m: any) => ({
        role: m.role as Message['role'],
        content: m.content,
      }))
    }
  }
  catch {
    // Backend unavailable, start empty
    MESSAGES.value = []
  }
}

export function newSession() {
  CURRENT_SESSION_ID.value = null
  MESSAGES.value = []
}

export async function switchSession(id: string) {
  CURRENT_SESSION_ID.value = id
  await loadCurrentSession()
}

declare global {
  interface WindowEventMap {
    token: CustomEvent<StreamChunk>
  }
}

export function chatStream(content: string) {
  MESSAGES.value.push({ role: 'user', content })

  API.chatStream(content).then(async ({ response }) => {
    MESSAGES.value.push({ role: 'assistant', content: '', generating: true })
    const message = MESSAGES.value[MESSAGES.value.length - 1]!

    for await (const chunk of response) {
      window.dispatchEvent(new CustomEvent('token', { detail: chunk }))

      if (chunk.type === 'content') {
        message.content += chunk.text
      }
      else if (chunk.type === 'reasoning') {
        message.content += `$》${chunk.text}《$`
      }
    }

    delete message.generating
  }).catch((err) => {
    MESSAGES.value.push({ role: 'system', content: `Error: ${err.message}` })
  })
}
