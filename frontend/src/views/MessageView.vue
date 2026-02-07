<script setup lang="ts">
import { onKeyStroke, useEventListener } from '@vueuse/core'
import { nextTick, onMounted, useTemplateRef } from 'vue'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'
import { chatStream, HISTORY } from '@/utils/chat'

const input = defineModel<string>()
const container = useTemplateRef('container')

function sendMessage() {
  if (input.value) {
    chatStream(input.value)
  }
  nextTick().then(() => container.value?.scrollToBottom())
}

useEventListener('token', () => {
  container.value?.scrollToBottom()
})
onKeyStroke('Enter', sendMessage)
onMounted(() => {
  container.value?.scrollToBottom()
})
</script>

<template>
  <div class="flex flex-col gap-8 overflow-hidden">
    <BoxContainer ref="container" class="w-full grow [&_:not(img)]:select-text">
      <MessageItem
        v-for="item, index in HISTORY" :key="index"
        :role="item.role" :content="item.content"
        class="py-2"
        :class="(item.generating && index === HISTORY.length - 1) || 'border-b'"
      />
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
