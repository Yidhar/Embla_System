import type { StreamChunk } from '@/utils/encoding'
import { useStorage } from '@vueuse/core'
import { ref } from 'vue'
import API from '@/api/core'

export interface Message {
  role: 'system' | 'user' | 'assistant' | 'info'
  content: string
  reasoning?: string
  generating?: boolean
  sender?: string
}

export const CURRENT_SESSION_ID = useStorage<string | null>('naga-session', null)
export const MESSAGES = ref<Message[]>([])
// 当前会话是否为临时会话（不持久化到磁盘，重启后消失）
export const IS_TEMPORARY_SESSION = ref(false)
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
      // 会话不存在（后端可能重启过），清空 session ID，从空白开始
      CURRENT_SESSION_ID.value = null
    }
  }
  // 无有效会话 ID，从空白开始
  MESSAGES.value = []
}

export function newSession() {
  CURRENT_SESSION_ID.value = null
  MESSAGES.value = []
  IS_TEMPORARY_SESSION.value = false
}

export function newTemporarySession() {
  CURRENT_SESSION_ID.value = null
  MESSAGES.value = []
  IS_TEMPORARY_SESSION.value = true
}

export async function switchSession(id: string) {
  CURRENT_SESSION_ID.value = id
  IS_TEMPORARY_SESSION.value = false
  await loadCurrentSession()
}

/** 将 ISO 时间字符串格式化为相对时间描述 */
export function formatRelativeTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1)
    return '刚刚'
  if (diffMin < 60)
    return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24)
    return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7)
    return `${diffDay}天前`
  return d.toLocaleDateString()
}

declare global {
  interface WindowEventMap {
    token: CustomEvent<StreamChunk>
  }
}
