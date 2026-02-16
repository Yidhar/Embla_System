<script setup lang="ts">
import ScrollPanel from 'primevue/scrollpanel'
import { useTemplateRef } from 'vue'
import back from '@/assets/icons/back.png'
import { useParallax } from '@/composables/useParallax'

const props = withDefaults(defineProps<{ parallax?: boolean, boxClass?: string }>(), { parallax: true, boxClass: 'w-3/5' })
const { transform: boxTransform } = useParallax({ rotateX: 3, rotateY: 3, translateX: 12, translateY: 8, invertRotate: true })

const scrollPanelRef = useTemplateRef<{
  scrollTop: (scrollTop: number) => void
}>('scrollPanelRef')

defineExpose({
  scrollToBottom() {
    scrollPanelRef.value?.scrollTop(Infinity)
  },
})
</script>

<template>
  <div
    class="flex min-h-0"
    :class="{ 'will-change-transform': parallax }"
    :style="parallax ? { transform: boxTransform } : undefined"
  >
    <div class="flex items-center">
      <img :src="back" class="w-[var(--nav-back-width)]" alt="" @click="$router.back">
    </div>
    <div class="box flex min-h-0 overflow-hidden" :class="boxClass">
      <ScrollPanel
        ref="scrollPanelRef"
        class="size-full"
        :pt="{
          barY: {
            class: 'w-2! rounded! bg-#373737! transition!',
          },
        }"
      >
        <div class="p-4 w-full">
          <slot />
        </div>
      </ScrollPanel>
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
