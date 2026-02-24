import API from '@/api/core'
import { CONFIG } from '@/utils/config'
import { live2dState, setEmotion } from '@/utils/live2dController'
import { CURRENT_SESSION_ID, IS_TEMPORARY_SESSION, MESSAGES } from '@/utils/session'
import { speak } from '@/utils/tts'

export interface ChatStreamOptions {
  skill?: string
  images?: string[]
}

function parseEmotionFromText(text: string): 'normal' | 'positive' | 'negative' | 'surprise' {
  if (text.includes('【正面情感】')) {
    return 'positive'
  }
  if (text.includes('【负面情感】')) {
    return 'negative'
  }
  if (text.includes('【惊讶情感】')) {
    return 'surprise'
  }
  return 'normal'
}

function formatToolStageLine(chunk: any): string {
  const phaseMap: Record<string, string> = {
    plan: 'PLAN',
    execute: 'EXECUTE',
    verify: 'VERIFY',
    repair: 'REPAIR',
  }
  const statusMap: Record<string, string> = {
    start: 'START',
    success: 'OK',
    error: 'ERROR',
    skip: 'SKIP',
  }
  const round = chunk.round ?? '?'
  const phase = phaseMap[chunk.phase || ''] || String(chunk.phase || 'UNKNOWN').toUpperCase()
  const status = statusMap[chunk.status || ''] || String(chunk.status || 'UNKNOWN').toUpperCase()
  const parts: string[] = []
  if (typeof chunk.actionable_calls === 'number') {
    parts.push(`calls=${chunk.actionable_calls}`)
  }
  if (typeof chunk.success_count === 'number' || typeof chunk.error_count === 'number') {
    const success = typeof chunk.success_count === 'number' ? chunk.success_count : 0
    const error = typeof chunk.error_count === 'number' ? chunk.error_count : 0
    parts.push(`ok=${success}, err=${error}`)
  }
  if (typeof chunk.threshold === 'number') {
    parts.push(`threshold=${chunk.threshold}`)
  }
  if (chunk.reason) {
    parts.push(`reason=${chunk.reason}`)
  }
  if (chunk.decision) {
    parts.push(`decision=${chunk.decision}`)
  }
  const detail = parts.length ? ` (${parts.join(', ')})` : ''
  return `> [R${round}] [${phase}] ${status}${detail}\n`
}

export function chatStream(content: string, options?: ChatStreamOptions): void {
  MESSAGES.value.push({ role: 'user', content: options?.images?.length ? `[截图x${options.images.length}] ${content}` : content })

  API.chatStream(content, {
    sessionId: CURRENT_SESSION_ID.value ?? undefined,
    disableTTS: true,
    skill: options?.skill,
    images: options?.images,
    temporary: IS_TEMPORARY_SESSION.value || undefined,
  }).then(async ({ sessionId, response }) => {
    if (sessionId) {
      CURRENT_SESSION_ID.value = sessionId
    }
    MESSAGES.value.push({ role: 'assistant', content: '', reasoning: '', generating: true })
    const message = MESSAGES.value[MESSAGES.value.length - 1]!
    let spokenContent = ''

    live2dState.value = 'thinking'
    for await (const chunk of response) {
      if (chunk.type === 'reasoning') {
        message.reasoning = (message.reasoning || '') + chunk.text
      }
      else if (chunk.type === 'content') {
        message.content += chunk.text
        spokenContent += chunk.text
        const emotion = parseEmotionFromText(chunk.text || '')
        if (emotion !== 'normal') {
          void setEmotion(emotion)
        }
      }
      else if (chunk.type === 'content_clean') {
        message.content = chunk.text || ''
        spokenContent = chunk.text || ''
      }
      else if (chunk.type === 'tool_calls') {
        const calls = chunk.calls || []
        const callDesc = calls.map((c: any) => {
          const name = c.service_name || c.agentType || 'tool'
          return `🔧 ${name}`
        }).join(', ')
        message.content += `\n\n> 正在执行工具: ${callDesc}...\n`
      }
      else if (chunk.type === 'tool_results') {
        const results = chunk.results || []
        for (const r of results) {
          const status = r.status === 'success' ? '✅' : '❌'
          const label = r.tool_name ? `${r.service_name}: ${r.tool_name}` : r.service_name
          message.content += `\n> ${status} ${label}\n`
        }
        message.content += '\n'
      }
      else if (chunk.type === 'tool_stage') {
        message.content += `${formatToolStageLine(chunk)}`
      }
      else if (chunk.type === 'round_start' && (chunk.round ?? 0) > 1) {
        message.content += '\n---\n\n'
      }
      else if (chunk.type === 'auth_expired') {
        message.content += chunk.text || '认证失败，请检查本地模型配置'
      }
      window.dispatchEvent(new CustomEvent('token', { detail: chunk.text || '' }))
    }

    delete message.generating
    if (!message.reasoning) {
      delete message.reasoning
    }

    if (CONFIG.value.system.voice_enabled && spokenContent) {
      speak(spokenContent).catch(() => {
        live2dState.value = 'idle'
      })
    }
    else {
      live2dState.value = 'idle'
    }
  }).catch((err) => {
    live2dState.value = 'idle'
    MESSAGES.value.push({ role: 'system', content: `Error: ${err.message}` })
  })
}
