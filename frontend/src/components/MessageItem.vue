<script setup lang="ts">
import type { Message } from '@/utils/session'
import { CONFIG } from '@/utils/config'
import Markdown from './Markdown.vue'

defineProps<Message>()

const COLOR_MAP = {
  system: 'bg-gray-500',
  user: 'bg-blue-500',
  assistant: 'bg-green-500',
}

const ROLE_MAP = {
  system: '系统',
  user: CONFIG.value.ui.user_name,
  assistant: CONFIG.value.system.ai_name,
}
</script>

<template>
  <div>
    <div class="flex flex-row gap-2 items-center">
      <div class="w-4 h-4 rounded-full" :class="sender ? 'bg-orange-500' : COLOR_MAP[role]" />
      <div class="font-bold text-white">{{ sender ?? ROLE_MAP[role] }}</div>
    </div>
    <div class="text-white mx-2 relative message-body">
      <Markdown :source="content || 'Generating...'" />
    </div>
  </div>
</template>

<style scoped>
.message-body {
  overflow-wrap: break-word;
  word-break: break-word;
  min-width: 0;
  overflow: hidden;
}

/* :deep() 穿透 v-html 渲染的所有子元素 */
.message-body :deep(*) {
  max-width: 100%;
  overflow-wrap: break-word;
  word-break: break-word;
}

.message-body :deep(pre) {
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.message-body :deep(table) {
  display: block;
  overflow-x: auto;
}

.message-body :deep(img) {
  max-width: 100%;
  height: auto;
}
</style>
