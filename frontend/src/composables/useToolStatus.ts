import { ref } from 'vue'
import API from '@/api/core'
import { triggerAction } from '@/utils/live2dController'
import { MESSAGES } from '@/utils/session'

export const toolMessage = ref('')
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const [status, clawdbot, live2d] = await Promise.allSettled([
      API.getToolStatus(),
      API.getClawdbotReplies(),
      API.getLive2dActions(),
    ])

    if (status.status === 'fulfilled') {
      toolMessage.value = status.value.visible ? status.value.message : ''
    }

    if (clawdbot.status === 'fulfilled' && clawdbot.value.replies?.length) {
      for (const reply of clawdbot.value.replies) {
        MESSAGES.value.push({
          role: 'assistant',
          content: reply,
          sender: 'AgentServer',
        })
      }
    }

    if (live2d.status === 'fulfilled' && live2d.value.actions?.length) {
      for (const action of live2d.value.actions) {
        triggerAction(action)
      }
    }
  }
  catch {
    // ignore polling errors
  }
}

export function startToolPolling() {
  if (timer)
    return
  poll()
  timer = setInterval(poll, 2000)
}

export function stopToolPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  toolMessage.value = ''
}
