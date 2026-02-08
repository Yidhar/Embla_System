<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AgentAPI from '@/api/agent'
import BoxContainer from '@/components/BoxContainer.vue'

interface Toolkit {
  name: string
  description: string
  tools: string[]
}

const toolkits = ref<Toolkit[]>([])
const loading = ref(true)
const error = ref('')
const expanded = ref<string | null>(null)

function toggle(name: string) {
  expanded.value = expanded.value === name ? null : name
}

onMounted(async () => {
  try {
    const res = await AgentAPI.getToolkits()
    toolkits.value = res.toolkits ?? []
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
        技能工坊
      </h2>

      <div v-if="loading" class="text-white/50">
        加载中...
      </div>
      <div v-else-if="error" class="text-red-400">
        {{ error }}
      </div>
      <div v-else-if="toolkits.length === 0" class="text-white/40">
        暂无可用工具包
      </div>
      <div v-else class="grid gap-3">
        <div
          v-for="tk in toolkits" :key="tk.name"
          class="box p-3 cursor-pointer hover:bg-white/5 transition"
          @click="toggle(tk.name)"
        >
          <div class="flex items-center justify-between">
            <div>
              <div class="font-bold">
                {{ tk.name }}
              </div>
              <div class="text-xs text-white/50">
                {{ tk.description }}
              </div>
            </div>
            <div class="text-white/30 text-sm">
              {{ tk.tools?.length ?? 0 }} 工具 {{ expanded === tk.name ? '▼' : '▶' }}
            </div>
          </div>
          <div v-if="expanded === tk.name && tk.tools?.length" class="mt-2 pl-2 border-l-2 border-white/20">
            <div v-for="tool in tk.tools" :key="tool" class="text-sm text-white/60 py-1">
              {{ tool }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </BoxContainer>
</template>
