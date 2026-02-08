<script lang="ts">
import { onKeyStroke, useEventListener } from '@vueuse/core'
import { nextTick, onMounted, onUnmounted, ref, useTemplateRef } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'
import { CURRENT_SESSION_ID, MESSAGES, loadCurrentSession, newSession } from '@/composables/useSession'
import { startToolPolling, stopToolPolling, toolMessage } from '@/composables/useToolStatus'
import { speak } from '@/composables/useTTS'
import { CONFIG } from '@/utils/config'

declare global {
  interface WindowEventMap {
    token: CustomEvent<string>
  }
}

export function chatStream(content: string) {
  MESSAGES.value.push({ role: 'user', content })

  startToolPolling()

  API.chatStream(content, {
    sessionId: CURRENT_SESSION_ID.value ?? undefined,
    disableTTS: true,
  }).then(async ({ sessionId, response }) => {
    if (sessionId) {
      CURRENT_SESSION_ID.value = sessionId
    }
    MESSAGES.value.push({ role: 'assistant', content: '', reasoning: '', generating: true })
    const message = MESSAGES.value[MESSAGES.value.length - 1]!

    for await (const chunk of response) {
      if (chunk.type === 'reasoning') {
        message.reasoning = (message.reasoning || '') + chunk.text
      } else {
        message.content += chunk.text
      }
      window.dispatchEvent(new CustomEvent('token', { detail: chunk.text }))
    }

    delete message.generating
    if (!message.reasoning) {
      delete message.reasoning
    }
    stopToolPolling()

    if (CONFIG.value.system.voice_enabled && message.content) {
      speak(message.content)
    }
  }).catch((err) => {
    MESSAGES.value.push({ role: 'system', content: `Error: ${err.message}` })
    stopToolPolling()
  })
}
</script>

<script setup lang="ts">
const input = defineModel<string>()
const containerRef = useTemplateRef('containerRef')
const fileInput = ref<HTMLInputElement | null>(null)

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

function handleNewSession() {
  newSession()
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  MESSAGES.value.push({ role: 'system', content: `正在上传文件: ${file.name}...` })
  try {
    const result = await API.uploadDocument(file)
    const msg = MESSAGES.value[MESSAGES.value.length - 1]!
    msg.content = `文件上传成功: ${file.name}`
    if (result.filePath) {
      chatStream(`请分析我刚上传的文件: ${file.name}`)
    }
  } catch (err: any) {
    const msg = MESSAGES.value[MESSAGES.value.length - 1]!
    msg.content = `文件上传失败: ${err.message}`
  }
  target.value = ''
}

onMounted(() => {
  loadCurrentSession()
  scrollToBottom()
})
onUnmounted(() => {
  stopToolPolling()
})
useEventListener('token', scrollToBottom)
onKeyStroke('Enter', sendMessage)
</script>

<template>
  <div class="flex flex-col gap-8 overflow-hidden">
    <BoxContainer ref="containerRef" class="w-full grow">
      <div class="grid gap-4">
        <MessageItem
          v-for="item, index in MESSAGES" :key="index"
          :role="item.role" :content="item.content"
          :reasoning="item.reasoning"
          :class="(item.generating && index === MESSAGES.length - 1) || 'border-b'"
        />
      </div>
    </BoxContainer>
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
