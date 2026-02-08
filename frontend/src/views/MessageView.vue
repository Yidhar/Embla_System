<script lang="ts">
import { onKeyStroke, useEventListener, useStorage } from '@vueuse/core'
import { nextTick, onMounted, useTemplateRef } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'

interface Message {
  role: 'system' | 'user' | 'assistant'
  content: string
  generating?: boolean
}

export const MESSAGES = useStorage<Message[]>('naga-messages', [])

declare global {
  interface WindowEventMap {
    token: CustomEvent<string>
  }
}

export function chatStream(content: string) {
  MESSAGES.value.push({ role: 'user', content })

  API.chatStream(content).then(async ({ response }) => {
    MESSAGES.value.push({ role: 'assistant', content: '', generating: true })
    const message = MESSAGES.value[MESSAGES.value.length - 1]!

    for await (const token of response) {
      message.content += token
      window.dispatchEvent(new CustomEvent('token', { detail: token }))
    }

    delete message.generating
  }).catch((err) => {
    MESSAGES.value.push({ role: 'system', content: `Error: ${err.message}` })
  })
}
</script>

<script setup lang="ts">
const input = defineModel<string>()
const containerRef = useTemplateRef('containerRef')

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

onMounted(scrollToBottom)
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
          :class="(item.generating && index === MESSAGES.length - 1) || 'border-b'"
        />
      </div>
    </BoxContainer>
    <div class="mx-[var(--nav-back-width)]">
      <div class="box">
        <input
          v-model="input"
          class="p-2 lh-none text-white w-full bg-transparent border-none outline-none" type="text"
          placeholder="Type a message..."
        >
      </div>
    </div>
  </div>
</template>
