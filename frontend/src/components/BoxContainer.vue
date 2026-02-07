<script setup lang="ts">
import { useTemplateRef } from 'vue'
import back from '@/assets/icons/back.png'

const container = useTemplateRef('container')

defineExpose({
  scrollToBottom() {
    if (container.value) {
      container.value.scrollTop = container.value?.scrollHeight
    }
  },
})
</script>

<template>
  <div class="flex overflow-hidden">
    <div class="flex items-center">
      <img :src="back" class="w-[var(--nav-back-width)]" alt="" @click="$router.back">
    </div>
    <div class="h-full box w-3/5">
      <div ref="container" class="h-full flex flex-col gap-4 overflow-auto p-4" v-bind="$attrs">
        <slot />
      </div>
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
