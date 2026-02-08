<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AgentAPI from '@/api/agent'
import BoxContainer from '@/components/BoxContainer.vue'

interface SessionItem {
  sessionId: string
  [key: string]: any
}

const sessions = ref<SessionItem[]>([])
const loading = ref(true)
const error = ref('')
const expanded = ref<string | null>(null)
const keyFacts = ref<Record<string, string[]>>({})
const loadingFacts = ref<string | null>(null)

async function toggle(sessionId: string) {
  if (expanded.value === sessionId) {
    expanded.value = null
    return
  }
  expanded.value = sessionId
  if (!keyFacts.value[sessionId]) {
    loadingFacts.value = sessionId
    try {
      const res = await AgentAPI.getSessionKeyFacts(sessionId)
      keyFacts.value[sessionId] = res.keyFacts ?? []
    } catch {
      keyFacts.value[sessionId] = []
    } finally {
      loadingFacts.value = null
    }
  }
}

onMounted(async () => {
  try {
    const res = await AgentAPI.getSessions()
    sessions.value = res.sessions ?? []
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
        记忆云海
      </h2>

      <div v-if="loading" class="text-white/50">
        加载中...
      </div>
      <div v-else-if="error" class="text-red-400">
        {{ error }}
      </div>
      <div v-else-if="sessions.length === 0" class="text-white/40">
        暂无会话记忆
      </div>
      <div v-else class="grid gap-3">
        <div
          v-for="s in sessions" :key="s.sessionId"
          class="box p-3 cursor-pointer hover:bg-white/5 transition"
          @click="toggle(s.sessionId)"
        >
          <div class="flex items-center justify-between">
            <div class="font-bold text-sm truncate max-w-3/4">
              {{ s.sessionId }}
            </div>
            <div class="text-white/30 text-xs">
              {{ expanded === s.sessionId ? '▼' : '▶' }}
            </div>
          </div>
          <div v-if="expanded === s.sessionId" class="mt-2 pl-2 border-l-2 border-white/20">
            <div v-if="loadingFacts === s.sessionId" class="text-white/40 text-sm">
              加载中...
            </div>
            <div v-else-if="keyFacts[s.sessionId]?.length" class="grid gap-1">
              <div v-for="(fact, i) in keyFacts[s.sessionId]" :key="i" class="text-sm text-white/60 py-1">
                {{ fact }}
              </div>
            </div>
            <div v-else class="text-white/40 text-sm">
              暂无关键事实
            </div>
          </div>
        </div>
      </div>
    </div>
  </BoxContainer>
</template>
