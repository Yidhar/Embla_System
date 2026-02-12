<script setup lang="ts">
import ScrollPanel from 'primevue/scrollpanel'
import { useTemplateRef } from 'vue'
import back from '@/assets/icons/back.png'
import { useParallax } from '@/composables/useParallax'

const { transform: boxTransform } = useParallax({ rotateX: 1.5, rotateY: 1.5, translateX: 6, translateY: 4 })

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
  <div class="flex overflow-hidden will-change-transform" :style="{ transform: boxTransform }">
    <div class="flex items-center">
      <img :src="back" class="w-[var(--nav-back-width)]" alt="" @click="$router.back">
    </div>
    <div class="box w-3/5 flex">
      <ScrollPanel
        ref="scrollPanelRef"
        class="size-full"
        :pt="{
          barY: {
            class: 'w-2! rounded! bg-#373737! transition!',
          },
        }"
      >
        <div class="p-4 size-full">
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
