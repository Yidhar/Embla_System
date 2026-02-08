import { ref } from 'vue'
import API from '@/api/core'

export const toolMessage = ref('')
let timer: ReturnType<typeof setInterval> | null = null

async function poll() {
  try {
    const status = await API.getToolStatus()
    toolMessage.value = status.visible ? status.message : ''
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
