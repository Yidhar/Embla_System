<script setup lang="ts">
import { CONFIG } from '@/utils/config'
import Markdown from './Markdown.vue'

defineProps<{
  role: 'system' | 'user' | 'assistant'
  content: string
}>()

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
      <div class="w-4 h-4 rounded-full" :class="COLOR_MAP[role]" />
      <div class="font-bold text-white">{{ ROLE_MAP[role] }}</div>
    </div>
    <div class="text-white mx-2 relative">
      <Markdown :source="content || 'Generating...'" />
    </div>
  </div>
</template>
