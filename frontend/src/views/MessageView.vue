<script setup lang="ts">
import { onKeyStroke } from '@vueuse/core'
import { nextTick, onMounted, ref, useTemplateRef } from 'vue'
import API from '@/api/core'
import MessageItem from '@/components/MessageItem.vue'

interface Message {
  role: 'system' | 'user' | 'assistant'
  content: string
  generating?: boolean
}

const history = ref<Message[]>([])
const input = defineModel<string>()
const container = useTemplateRef<HTMLDivElement>('container')

function sendMessage() {
  if (!input.value)
    return

  history.value.push({ role: 'user', content: input.value })

  API.chatStream(input.value).then(async ({ sessionId, response }) => {
    history.value.push({
      role: 'assistant' as const,
      content: `---\nsessionId: ${sessionId}\n---\n`,
      generating: true,
    })
    const message = history.value[history.value.length - 1]!
    for await (const chunk of response) {
      message.content += chunk
      scrollToBottom()
    }
    delete message.generating
  }).catch((err) => {
    history.value.push({ role: 'system', content: `Error: ${err.message}` })
  })

  input.value = ''

  nextTick().then(scrollToBottom)
}

function scrollToBottom() {
  if (container.value) {
    container.value.scrollTop = container.value?.scrollHeight
  }
}

onKeyStroke('Enter', sendMessage)

onMounted(() => {
  input.value = 'Hello, NagaAgent!'
  sendMessage()
})
</script>

<template>
  <div class="px-10% py-5% flex flex-col items-center justify-center gap-8 box-border">
    <div class="w-full grow overflow-hidden">
      <div class="w-60% h-full box">
        <div ref="container" class="h-full flex flex-col gap-4 overflow-auto p-4">
          <MessageItem
            v-for="item, index in history" :key="index"
            :role="item.role" :content="item.content"
            :class="item.generating ? '' : 'border-b'"
          />
        </div>
      </div>
    </div>
    <div class="w-full box">
      <input
        v-model="input"
        class="p-2 pt-1.5 lh-none text-white w-full bg-transparent border-none outline-none" type="text"
        placeholder="Type a message..."
      >
    </div>
  </div>
</template>

<style scoped>
::-webkit-scrollbar {
  background-color: transparent;
  width: 6px;
}

::-webkit-scrollbar-thumb {
  background-color: #fff3;
  border-radius: 3px;
  height: 20%;
}
</style>
