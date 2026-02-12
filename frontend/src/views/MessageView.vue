<script lang="ts">
import { onKeyStroke, useEventListener } from '@vueuse/core'
import { nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'
import { startToolPolling, stopToolPolling, toolMessage } from '@/composables/useToolStatus'
import { CONFIG } from '@/utils/config'
import { live2dState } from '@/utils/live2dController'
import { CURRENT_SESSION_ID, loadCurrentSession, MESSAGES, newSession, switchSession } from '@/utils/session'
import { isPlaying, speak } from '@/utils/tts'

export function chatStream(content: string) {
  MESSAGES.value.push({ role: 'user', content })

  API.chatStream(content, {
    sessionId: CURRENT_SESSION_ID.value ?? undefined,
    disableTTS: true,
  }).then(async ({ sessionId, response }) => {
    if (sessionId) {
      CURRENT_SESSION_ID.value = sessionId
    }
    MESSAGES.value.push({ role: 'assistant', content: '', reasoning: '', generating: true })
    const message = MESSAGES.value[MESSAGES.value.length - 1]!
    // 追踪纯LLM内容（不含工具状态标记），用于TTS朗读
    let spokenContent = ''

    live2dState.value = 'thinking'

    for await (const chunk of response) {
      if (chunk.type === 'reasoning') {
        message.reasoning = (message.reasoning || '') + chunk.text
      }
      else if (chunk.type === 'content') {
        message.content += chunk.text
        spokenContent += chunk.text
      }
      else if (chunk.type === 'content_clean') {
        // 后端解析出工具调用后，发送清理后的纯文本替换掉含有 ```tool``` 块的原文
        message.content = chunk.text || ''
        spokenContent = chunk.text || ''
      }
      else if (chunk.type === 'tool_calls') {
        // 显示工具调用状态
        const calls = chunk.calls || []
        const callDesc = calls.map((c: any) => {
          const name = c.service_name || c.agentType || 'tool'
          return `🔧 ${name}`
        }).join(', ')
        message.content += `\n\n> 正在执行工具: ${callDesc}...\n`
      }
      else if (chunk.type === 'tool_results') {
        // 显示工具结果摘要
        const results = chunk.results || []
        for (const r of results) {
          const status = r.status === 'success' ? '✅' : '❌'
          const label = r.tool_name ? `${r.service_name}: ${r.tool_name}` : r.service_name
          message.content += `\n> ${status} ${label}\n`
        }
        message.content += '\n'
      }
      else if (chunk.type === 'round_start' && (chunk.round ?? 0) > 1) {
        // 多轮分隔
        message.content += '\n---\n\n'
      }
      // round_end 不需要特殊处理
      window.dispatchEvent(new CustomEvent('token', { detail: chunk.text || '' }))
    }

    delete message.generating
    if (!message.reasoning) {
      delete message.reasoning
    }

    if (CONFIG.value.system.voice_enabled && spokenContent) {
      live2dState.value = 'talking'
      speak(spokenContent)
    }
    else {
      live2dState.value = 'idle'
    }
  }).catch((err) => {
    live2dState.value = 'idle'
    MESSAGES.value.push({ role: 'system', content: `Error: ${err.message}` })
  })
}
</script>

<script setup lang="ts">
const input = defineModel<string>()
const containerRef = useTemplateRef('containerRef')
const fileInput = ref<HTMLInputElement | null>(null)

// TTS 结束后回到 idle
watch(isPlaying, (playing) => {
  if (!playing && live2dState.value === 'talking') {
    live2dState.value = 'idle'
  }
})

function scrollToBottom() {
  containerRef.value?.scrollToBottom()
}

function sendMessage() {
  if (input.value) {
    chatStream(input.value)
    nextTick().then(scrollToBottom)
    input.value = ''
  }
}

onMounted(() => {
  loadCurrentSession()
  startToolPolling()
  scrollToBottom()
})
onUnmounted(() => {
  stopToolPolling()
})
useEventListener('token', scrollToBottom)
onKeyStroke('Enter', (e) => {
  if (e.isComposing) return
  sendMessage()
})

// Session history
const showHistory = ref(false)
const sessions = ref<Array<{
  sessionId: string
  createdAt: string
  lastActiveAt: string
  conversationRounds: number
}>>([])
const loadingSessions = ref(false)

async function fetchSessions() {
  loadingSessions.value = true
  try {
    const res = await API.getSessions()
    sessions.value = res.sessions ?? []
  }
  catch {
    sessions.value = []
  }
  loadingSessions.value = false
}

function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) {
    fetchSessions()
  }
}

async function handleSwitchSession(id: string) {
  await switchSession(id)
  showHistory.value = false
  nextTick().then(scrollToBottom)
}

async function handleDeleteSession(id: string) {
  try {
    await API.deleteSession(id)
    sessions.value = sessions.value.filter(s => s.sessionId !== id)
    if (CURRENT_SESSION_ID.value === id) {
      newSession()
    }
  }
  catch { /* ignore */ }
}

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1)
    return '刚刚'
  if (diffMin < 60)
    return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24)
    return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7)
    return `${diffDay} 天前`
  return d.toLocaleDateString()
}

function handleNewSession() {
  newSession()
  showHistory.value = false
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file)
    return

  MESSAGES.value.push({ role: 'system', content: `正在上传文件: ${file.name}...` })
  try {
    const result = await API.uploadDocument(file)
    const msg = MESSAGES.value[MESSAGES.value.length - 1]!
    msg.content = `文件上传成功: ${file.name}`
    if (result.filePath) {
      chatStream(`请分析我刚上传的文件: ${file.name}`)
    }
  }
  catch (err: any) {
    const msg = MESSAGES.value[MESSAGES.value.length - 1]!
    msg.content = `文件上传失败: ${err.message}`
  }
  target.value = ''
}
</script>

<template>
  <div class="flex flex-col gap-8 overflow-hidden relative">
    <BoxContainer ref="containerRef" class="w-full grow">
      <div class="grid gap-4 pb-8">
        <MessageItem
          v-for="item, index in MESSAGES" :key="index"
          :role="item.role" :content="item.content"
          :reasoning="item.reasoning" :sender="item.sender"
          :class="(item.generating && index === MESSAGES.length - 1) || 'border-b'"
        />
      </div>
    </BoxContainer>

    <!-- Session History Panel -->
    <Transition name="slide-up">
      <div v-if="showHistory" class="session-panel">
        <div class="flex items-center justify-between px-3 py-2 border-b border-white/10">
          <span class="text-white/70 text-sm font-bold">对话历史</span>
          <button
            class="text-white/40 hover:text-white/80 bg-transparent border-none cursor-pointer text-xs"
            @click="showHistory = false"
          >
            关闭
          </button>
        </div>
        <div class="overflow-y-auto max-h-48">
          <div v-if="loadingSessions" class="text-white/40 text-xs text-center py-4">
            加载中...
          </div>
          <div v-else-if="sessions.length === 0" class="text-white/40 text-xs text-center py-4">
            暂无历史对话
          </div>
          <div
            v-for="s in sessions" :key="s.sessionId"
            class="session-item"
            :class="{ 'bg-white/10': s.sessionId === CURRENT_SESSION_ID }"
            @click="handleSwitchSession(s.sessionId)"
          >
            <div class="flex-1 min-w-0">
              <div class="text-white/80 text-sm truncate">
                {{ s.sessionId.slice(0, 8) }}...
              </div>
              <div class="text-white/40 text-xs">
                {{ formatTime(s.lastActiveAt) }} · {{ s.conversationRounds }} 轮对话
              </div>
            </div>
            <button
              class="text-white/30 hover:text-red-400 bg-transparent border-none cursor-pointer text-xs shrink-0 ml-2"
              title="删除"
              @click.stop="handleDeleteSession(s.sessionId)"
            >
              x
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <div v-if="toolMessage" class="mx-[var(--nav-back-width)] text-white/50 text-xs px-2 py-1">
      {{ toolMessage }}
    </div>
    <div class="mx-[var(--nav-back-width)]">
      <div class="box flex items-center gap-2">
        <button
          class="p-2 text-white/60 hover:text-white bg-transparent border-none cursor-pointer text-sm shrink-0"
          title="新建对话"
          @click="handleNewSession"
        >
          +
        </button>
        <button
          class="p-2 text-white/60 hover:text-white bg-transparent border-none cursor-pointer text-sm shrink-0"
          :class="{ 'text-white!': showHistory }"
          title="对话历史"
          @click="toggleHistory"
        >
          H
        </button>
        <input
          v-model="input"
          class="p-2 lh-none text-white w-full bg-transparent border-none outline-none"
          type="text"
          placeholder="Type a message..."
        >
        <button
          class="p-2 text-white/60 hover:text-white bg-transparent border-none cursor-pointer text-sm shrink-0"
          title="上传文件"
          @click="triggerUpload"
        >
          +F
        </button>
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          @change="handleFileUpload"
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-panel {
  position: absolute;
  left: var(--nav-back-width);
  right: 0;
  bottom: 5rem;
  background: rgba(30, 30, 30, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  backdrop-filter: blur(12px);
  z-index: 10;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.2s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
