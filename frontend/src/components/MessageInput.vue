<script setup lang="ts">
const input = defineModel<string>()
</script>

<template>
  <div class="box">
    <input class="text-white w-full bg-transparent border-none outline-none" v-model="input" type="text"
      placeholder="Type a message..." />
  </div>
</template>
