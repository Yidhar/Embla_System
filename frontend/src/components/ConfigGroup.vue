<script setup lang="ts">
import { AccordionContent, AccordionHeader, AccordionPanel } from 'primevue'

defineProps<{
  name?: string
  recoverDefault?: () => void
}>()
</script>

<template>
  <AccordionPanel :value="name">
    <AccordionHeader>
      <div class="w-full flex justify-between items-center pr-4">
        <slot name="header">{{ name }}</slot>
      </div>
    </AccordionHeader>
    <AccordionContent>
      <slot />
    </AccordionContent>
  </AccordionPanel>
</template>
