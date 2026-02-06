<script setup lang="ts">
import { useLink } from 'vue-router'
import brain from '@/assets/icons/brain.png'
import chip from '@/assets/icons/chip.png'
import naga from '@/assets/icons/naga.png'
import toolkit from '@/assets/icons/toolkit.png'
import ArkButton from '@/components/ArkButton.vue'

const chat = useLink({ to: '/chat' })
</script>

<template>
  <div class="flex flex-col items-start justify-center pl-20%">
    <div class="grid grid-rows-3 gap-3 *:gap-3 panel">
      <div class="relative size-full">
        <ArkButton class="size-full" :icon="naga" @click="chat.navigate">
          <div class="size-full flex items-center justify-end mr-4em">
            对话
          </div>
        </ArkButton>
        <div class="absolute -left-2 right-1/2 top-2 bottom-2">
          <ArkButton class="size-full bg-blue">
            <div class="size-full text-center">
              I'm Overlay!
            </div>
          </ArkButton>
        </div>
      </div>
      <div class="grid grid-cols-2 -translate-x-1/5">
        <ArkButton :icon="brain" title="记忆<br>云海" />
        <ArkButton :icon="toolkit" title="功能" subtitle="工具市场" />
      </div>
      <div class="grid grid-cols-2">
        <div class="flex flex-col">
          <div class="bg-#363837 text-white p-2 text-sm font-sans">
            参数设置
          </div>
          <div class="grow grid grid-cols-2 font-serif font-bold lh-none">
            <ArkButton class="hover:z-1">
              <div class="size-full text-lg">对话模型</div>
            </ArkButton>
            <ArkButton>
              <div class="size-full text-lg">记忆链接</div>
            </ArkButton>
          </div>
        </div>
        <ArkButton :icon="chip">
          <div class="size-full flex justify-center pt-10%">
            终端设置
          </div>
        </ArkButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  transform: perspective(200px) rotateY(2deg) scale(1.2);
}
</style>
