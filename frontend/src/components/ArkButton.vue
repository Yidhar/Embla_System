<script setup lang="ts">
defineProps<{
  subtitle?: string
  icon?: string
}>()
</script>

<template>
  <button class="text-black bg-white bg-opacity-80 relative">
    <div class="px-3 py-2 flex flex gap-12 justify-between">
      <div class="w-full  flex flex-col gap-2 flex justify-center">
        <span class="text-2vw font-bold font-serif lh-none">
          <slot />
        </span>
        <span v-if="subtitle" class="text-1.2vw c-gray-800 op-40 font-sans">
          {{ subtitle }}
        </span>
      </div>
      <img v-if="icon" :src="icon" class="w-5vw">
    </div>
  </button>
</template>
