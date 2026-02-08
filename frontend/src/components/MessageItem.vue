<script setup lang="ts">
import { ref } from 'vue'
import { CONFIG } from '@/utils/config'
import Markdown from './Markdown.vue'

defineProps<{
  role: 'system' | 'user' | 'assistant'
  content: string
  reasoning?: string
}>()

const showReasoning = ref(false)

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
    <div v-if="reasoning" class="mx-2 mt-1">
      <button
        class="text-xs text-white/40 hover:text-white/70 bg-transparent border-none cursor-pointer p-0"
        @click="showReasoning = !showReasoning"
      >
        {{ showReasoning ? '▼' : '▶' }} 思考过程
      </button>
      <div
        v-if="showReasoning"
        class="text-white/50 text-sm mt-1 pl-2 border-l-2 border-white/20"
      >
        <Markdown :source="reasoning" />
      </div>
    </div>
    <div class="text-white mx-2 relative">
      <Markdown :source="content || 'Generating...'" />
    </div>
  </div>
</template>
