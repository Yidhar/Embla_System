<script setup lang="ts">
import type { Message } from '@/utils/session'
import { ref } from 'vue'
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

const reasoningExpanded = ref(true)
</script>

<template>
  <div>
    <div class="flex flex-row gap-2 items-center">
      <div class="w-4 h-4 rounded-full" :class="sender ? 'bg-orange-500' : COLOR_MAP[role]" />
      <div class="font-bold text-white">{{ sender ?? ROLE_MAP[role] }}</div>
    </div>
    <!-- 思考过程（reasoning）：生成中展开显示，生成完成后可折叠 -->
    <div v-if="reasoning" class="mx-2 mt-1 reasoning-block">
      <div
        class="reasoning-header"
        @click="reasoningExpanded = !reasoningExpanded"
      >
        <span v-if="generating" class="reasoning-spinner" />
        <span>{{ generating ? '思考中' : '思考过程' }}</span>
        <span v-if="!generating" class="reasoning-toggle">{{ reasoningExpanded ? '收起' : '展开' }}</span>
      </div>
      <div v-show="reasoningExpanded" class="reasoning-content">
        <Markdown :source="reasoning" />
      </div>
    </div>
    <div class="text-white mx-2 relative message-body">
      <Markdown :source="content || (reasoning ? '' : 'Generating...')" />
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

/* 思考过程区块 */
.reasoning-block {
  border-left: 2px solid rgba(212, 175, 55, 0.4);
  margin-bottom: 0.5rem;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  color: rgba(212, 175, 55, 0.7);
  cursor: pointer;
  user-select: none;
}

.reasoning-header:hover {
  color: rgba(212, 175, 55, 0.9);
}

.reasoning-spinner {
  width: 0.6rem;
  height: 0.6rem;
  border: 1.5px solid rgba(212, 175, 55, 0.3);
  border-top-color: rgba(212, 175, 55, 0.8);
  border-radius: 50%;
  animation: reasoning-spin 0.8s linear infinite;
}

@keyframes reasoning-spin {
  to { transform: rotate(360deg); }
}

.reasoning-toggle {
  margin-left: auto;
  font-size: 0.7rem;
  opacity: 0.6;
}

.reasoning-content {
  padding: 0.25rem 0.75rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
  max-height: 300px;
  overflow-y: auto;
}

.reasoning-content :deep(*) {
  max-width: 100%;
  overflow-wrap: break-word;
  word-break: break-word;
}
</style>
