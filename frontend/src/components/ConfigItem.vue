<script setup lang="ts">
import Markdown from './Markdown.vue'

withDefaults(defineProps<{
  name: string
  description?: string
  layout?: 'row' | 'column'
}>(), {
  layout: 'row',
})
</script>

<template>
  <label :class="layout === 'row' ? 'grid grid-cols-2' : 'flex flex-col'">
    <div class="flex flex-col justify-center">
      <div class="font-bold">{{ name }}</div>
      <Markdown
        v-if="description" :source="description"
        class="text-sm text-gray-500 *:mt-0.5 *:mb-2"
      />
    </div>
    <div class="flex flex-col *:w-full justify-center">
      <slot />
    </div>
  </label>
</template>
