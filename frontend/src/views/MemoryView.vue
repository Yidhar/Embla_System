<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CONFIG } from '@/utils/config'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'

const memoryStats = ref<Record<string, any> | null>(null)
const testResult = ref<string | null>(null)
const testing = ref(false)

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    const res = await API.getMemoryStats()
    const stats = res.memoryStats ?? res
    if (stats.enabled === false) {
      testResult.value = `未启用: ${stats.message || '请先启用知识图谱'}`
    } else {
      memoryStats.value = stats
      testResult.value = `连接成功 (五元组: ${stats.totalQuintuples ?? 0})`
    }
  } catch (e: any) {
    testResult.value = `连接失败: ${e.message}`
  } finally {
    testing.value = false
  }
}

function sliderToThreshold(val: number): number {
  return Math.round(val * 100) / 100
}

onMounted(() => {
  testConnection()
})
</script>

<template>
  <BoxContainer class="w-full h-full overflow-y-auto">
    <div class="text-white">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-bold">
          记忆链接
        </h2>
        <button
          class="px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded text-sm transition"
          :disabled="testing"
          @click="testConnection"
        >
          {{ testing ? '测试中...' : '测试连接' }}
        </button>
      </div>

      <!-- Test Result -->
      <div v-if="testResult" class="mb-4 p-2 rounded text-sm" :class="testResult.startsWith('连接成功') ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'">
        {{ testResult }}
      </div>

      <!-- Settings -->
      <div class="grid gap-4">
        <!-- Enabled -->
        <div class="box p-3 flex items-center justify-between">
          <div>
            <div class="font-bold text-sm">
              启用知识图谱
            </div>
            <div class="text-xs text-white/40">
              启用 GRAG 记忆系统
            </div>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="CONFIG.grag.enabled"
              type="checkbox"
              class="sr-only peer"
            >
            <div class="w-9 h-5 bg-white/20 peer-focus:outline-none rounded-full peer peer-checked:bg-green-500 after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
          </label>
        </div>

        <!-- Auto Extract -->
        <div class="box p-3 flex items-center justify-between">
          <div>
            <div class="font-bold text-sm">
              自动提取
            </div>
            <div class="text-xs text-white/40">
              自动从对话中提取五元组知识
            </div>
          </div>
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              v-model="CONFIG.grag.auto_extract"
              type="checkbox"
              class="sr-only peer"
            >
            <div class="w-9 h-5 bg-white/20 peer-focus:outline-none rounded-full peer peer-checked:bg-green-500 after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
          </label>
        </div>

        <!-- Context Length -->
        <div class="box p-3">
          <div class="flex items-center justify-between mb-2">
            <div>
              <div class="font-bold text-sm">
                上下文长度
              </div>
              <div class="text-xs text-white/40">
                最近对话窗口大小 (1-20)
              </div>
            </div>
            <span class="text-sm font-bold">{{ CONFIG.grag.context_length }}</span>
          </div>
          <input
            v-model.number="CONFIG.grag.context_length"
            type="range"
            min="1"
            max="20"
            step="1"
            class="w-full accent-teal-500"
          >
        </div>

        <!-- Similarity Threshold -->
        <div class="box p-3">
          <div class="flex items-center justify-between mb-2">
            <div>
              <div class="font-bold text-sm">
                相似度阈值
              </div>
              <div class="text-xs text-white/40">
                RAG 知识检索匹配阈值 (0.0 - 1.0)
              </div>
            </div>
            <span class="text-sm font-bold">{{ sliderToThreshold(CONFIG.grag.similarity_threshold) }}</span>
          </div>
          <input
            v-model.number="CONFIG.grag.similarity_threshold"
            type="range"
            min="0"
            max="1"
            step="0.05"
            class="w-full accent-teal-500"
          >
        </div>

        <!-- Neo4j URI -->
        <div class="box p-3">
          <div class="font-bold text-sm mb-1">
            Neo4j URI
          </div>
          <div class="text-xs text-white/40 mb-2">
            图数据库连接地址
          </div>
          <input
            v-model="CONFIG.grag.neo4j_uri"
            type="text"
            class="w-full bg-white/10 border border-white/20 rounded px-3 py-1.5 text-sm text-white outline-none focus:border-white/40"
            placeholder="neo4j://127.0.0.1:7687"
          >
        </div>

        <!-- Neo4j User -->
        <div class="box p-3">
          <div class="font-bold text-sm mb-1">
            Neo4j 用户名
          </div>
          <input
            v-model="CONFIG.grag.neo4j_user"
            type="text"
            class="w-full bg-white/10 border border-white/20 rounded px-3 py-1.5 text-sm text-white outline-none focus:border-white/40"
            placeholder="neo4j"
          >
        </div>

        <!-- Neo4j Password -->
        <div class="box p-3">
          <div class="font-bold text-sm mb-1">
            Neo4j 密码
          </div>
          <input
            v-model="CONFIG.grag.neo4j_password"
            type="password"
            class="w-full bg-white/10 border border-white/20 rounded px-3 py-1.5 text-sm text-white outline-none focus:border-white/40"
            placeholder="••••••••"
          >
        </div>
      </div>

      <!-- Memory Stats -->
      <div v-if="memoryStats && memoryStats.enabled !== false" class="mt-6">
        <h3 class="text-sm font-bold text-white/70 mb-2">
          记忆统计
        </h3>
        <div class="grid grid-cols-2 gap-2">
          <div v-for="(value, key) in memoryStats" :key="key" class="box p-2">
            <div class="text-xs text-white/40">
              {{ key }}
            </div>
            <div class="text-sm font-bold">
              {{ typeof value === 'object' ? JSON.stringify(value) : value }}
            </div>
          </div>
        </div>
      </div>

      <div class="mt-4 text-xs text-white/30">
        设置修改后自动保存
      </div>
    </div>
  </BoxContainer>
</template>
