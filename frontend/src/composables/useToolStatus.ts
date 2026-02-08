import { ref } from 'vue'
import API from '@/api/core'
import { MESSAGES } from '@/composables/useSession'

export const toolMessage = ref('')
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const [status, clawdbot] = await Promise.allSettled([
      API.getToolStatus(),
      API.getClawdbotReplies(),
    ])

    if (status.status === 'fulfilled') {
      toolMessage.value = status.value.visible ? status.value.message : ''
    }

    if (clawdbot.status === 'fulfilled' && clawdbot.value.replies?.length) {
      for (const reply of clawdbot.value.replies) {
        MESSAGES.value.push({
          role: 'assistant',
          content: `**ClawdBot:** ${reply}`,
        })
      }
    }
  } catch {
    // ignore polling errors
  }
}

export function startToolPolling() {
  if (timer) return
  poll()
  timer = setInterval(poll, 1000)
}

export function stopToolPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  toolMessage.value = ''
}
