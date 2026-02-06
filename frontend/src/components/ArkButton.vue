<script setup lang="ts">
defineProps<{
  title?: string
  subtitle?: string
  icon?: string
}>()
</script>

<template>
  <button
    class="text-black bg-#fffe backdrop-blur-md relative transition-all duration-150 ease-out shadow hover:scale-102"
  >
    <img v-if="icon" :src="icon" class="size-16 pl-2 absolute right-4 top-1/2 -translate-y-1/2">
    <div class="flex text-3xl font-bold font-serif lh-none">
      <slot>
        <div class="px-2 py-4 pr-5em flex flex-col gap-2 justify-center">
          <div v-html="title" />
          <div v-if="subtitle" class="text-base c-gray-800 op-40 font-sans lh-none">
            {{ subtitle }}
          </div>
        </div>
      </slot>
    </div>
  </button>
</template>
