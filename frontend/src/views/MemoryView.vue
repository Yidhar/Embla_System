<script setup lang="ts">
import { onMounted, ref } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'

const memoryStats = ref<Record<string, any> | null>(null)
const contextStats = ref<Record<string, any> | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const [mem, ctx] = await Promise.allSettled([
      API.getMemoryStats(),
      API.getContextStats(7),
    ])
    if (mem.status === 'fulfilled') memoryStats.value = mem.value.memoryStats ?? mem.value
    if (ctx.status === 'fulfilled') contextStats.value = ctx.value
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <BoxContainer class="w-full h-full">
    <div class="text-white">
      <h2 class="text-lg font-bold mb-4">
        记忆链接
      </h2>

      <div v-if="loading" class="text-white/50">
        加载中...
      </div>
      <div v-else-if="error" class="text-red-400">
        {{ error }}
      </div>
      <template v-else>
        <div class="mb-6">
          <h3 class="text-sm font-bold text-white/70 mb-2">
            GRAG 知识图谱
          </h3>
          <div v-if="memoryStats" class="grid grid-cols-2 gap-2">
            <template v-if="memoryStats.enabled === false">
              <div class="col-span-2 text-white/40 text-sm">
                {{ memoryStats.message || '记忆系统未启用' }}
              </div>
            </template>
            <template v-else>
              <div v-for="(value, key) in memoryStats" :key="key" class="box p-3">
                <div class="text-xs text-white/40">
                  {{ key }}
                </div>
                <div class="text-lg font-bold">
                  {{ value }}
                </div>
              </div>
            </template>
          </div>
          <div v-else class="text-white/40 text-sm">
            无法获取记忆统计
          </div>
        </div>

        <div>
          <h3 class="text-sm font-bold text-white/70 mb-2">
            对话统计 (近7天)
          </h3>
          <div v-if="contextStats" class="grid grid-cols-2 gap-2">
            <div v-for="(value, key) in contextStats" :key="key" class="box p-3">
              <div class="text-xs text-white/40">
                {{ key }}
              </div>
              <div class="text-lg font-bold">
                {{ typeof value === 'object' ? JSON.stringify(value) : value }}
              </div>
            </div>
          </div>
          <div v-else class="text-white/40 text-sm">
            无法获取对话统计
          </div>
        </div>
      </template>
    </div>
  </BoxContainer>
</template>
