<script setup lang="ts">
import ArkButton from '@/components/ArkButton.vue'
</script>

<template>
  <div class="flex flex-col items-start justify-center pl-10%">
    <div class="grid grid-rows-3 gap-3 [&>.grid]:gap-3 panel">
      <RouterLink to="/chat">
        <ArkButton class="size-full" icon="/assets/icons/naga.png">
          <div class="absolute bottom-0 right-0 size-full justify-center flex items-center">
            对话
          </div>
        </ArkButton>
      </RouterLink>
      <div class="grid grid-cols-2 translate-x-16">
        <ArkButton icon="/assets/icons/brain.png">
          记忆<br>云海
        </ArkButton>
        <ArkButton icon="/assets/icons/toolkit.png" subtitle="工具市场">
          功能
        </ArkButton>
      </div>
      <div class="grid grid-cols-2">
        <div class="flex flex-col">
          <div class="bg-#363837 text-white text-end p-2">
            参数设置
          </div>
          <div class="grow grid grid-cols-2 font-serif font-bold lh-none">
            <ArkButton class="mr-1">
              <span class="p-auto text-1.5vw">对话模型</span>
            </ArkButton>
            <ArkButton>
              <span class="p-auto text-1.5vw">记忆链接</span>
            </ArkButton>
          </div>
        </div>
        <ArkButton icon="/assets/icons/chip.png">
          <div class="absolute bottom-0 right-0 w-full pb-3">
            终端设置
          </div>
        </ArkButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  transform: perspective(100px) rotateY(1deg);
  zoom: 1.2;
}
</style>
