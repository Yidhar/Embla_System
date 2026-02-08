<script lang="ts">
import type { MarketItem as Skill } from '@/api/core'
import { FileUpload, Listbox } from 'primevue'
import { ref } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'

const SKILLS = ref<Skill[]>([])

API.getMarketItems().then((res) => {
  SKILLS.value = res.items
})
</script>

<script setup lang="ts">
</script>

<template>
  <BoxContainer>
    <div class="h-full flex flex-col gap-4">
      <div class="flex items-center justify-between">
        <div class="font-bold text-xl">技能工坊</div>
        <FileUpload mode="basic" multiple auto choose-label="上传 Skill" />
      </div>
      <div class="overflow-hidden">
        <Listbox :options="SKILLS" class="size-full flex! flex-col" scroll-height="100%" filter>
          <template #option="{ option }">
            <div class="flex items-center justify-center w-full h-full">
              {{ option }}
            </div>
          </template>
        </Listbox>
      </div>
    </div>
  </BoxContainer>
</template>
