<script setup lang="ts">
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
</script>

<template>
  <div>
    <div class="flex flex-row gap-2 items-center">
      <div class="w-4 h-4 rounded-full" :class="COLOR_MAP[role]" />
      <div class="font-bold text-white">{{ role }}</div>
    </div>
    <div class="text-white mx-2 relative">
      <Markdown :source="content || 'Generating...'" />
    </div>
  </div>
</template>
