<script setup lang="ts">
import { onKeyStroke, useEventListener } from '@vueuse/core'
import { nextTick, onMounted, useTemplateRef } from 'vue'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'
import { chatStream, MESSAGES } from '@/utils/session'

const input = defineModel<string>()
const containerRef = useTemplateRef<{
  scrollToBottom: () => void
}>('containerRef')

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
      <div class="grid gap-4 pb-8">
        <MessageItem
          v-for="item, index in MESSAGES" :key="index" v-bind="item"
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
