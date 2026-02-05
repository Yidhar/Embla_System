<script setup lang="ts">
const input = defineModel<string>()
</script>

<template>
  <div class="box">
    <input
      v-model="input" class="text-white w-full bg-transparent border-none outline-none" type="text"
      placeholder="Type a message..."
    >
  </div>
</template>
