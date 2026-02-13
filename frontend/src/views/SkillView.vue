<script setup lang="ts">
import type { MarketItem } from '@/api/core'
import { useStorage } from '@vueuse/core'
import { Accordion } from 'primevue'
import { ref } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import McpAddDialog from '@/components/McpAddDialog.vue'
import SkillAddDialog from '@/components/SkillAddDialog.vue'

interface McpService {
  name: string
  displayName: string
  description: string
  source: 'builtin' | 'mcporter'
  available: boolean
}

const accordionValue = useStorage('accordion-skill', ['mcp', 'skills'])

// ── MCP 服务 ──
const mcpServices = ref<McpService[]>([])
const mcpLoading = ref(true)
const showMcpDialog = ref(false)

function loadMcpServices() {
  mcpLoading.value = true
  API.getMcpServices().then((res) => {
    mcpServices.value = (res.services ?? []).filter(s => s.available)
  }).catch(() => {
    mcpServices.value = []
  }).finally(() => {
    mcpLoading.value = false
  })
}
loadMcpServices()

async function onMcpConfirm(data: { name: string, config: Record<string, any> }) {
  try {
    await API.importMcpConfig(data.name, data.config)
    showMcpDialog.value = false
    loadMcpServices()
  }
  catch (e: any) {
    alert(`导入失败: ${e.message}`)
  }
}

// ── 技能仓库 ──
const skills = ref<MarketItem[]>([])
const installing = ref<string | null>(null)
const showSkillDialog = ref(false)

API.getMarketItems().then((res) => {
  skills.value = res.items ?? []
}).catch(() => {})

async function installItem(item: MarketItem) {
  installing.value = item.id
  try {
    await API.installMarketItem(item.id)
    item.installed = true
  }
  catch (e: any) {
    alert(`安装失败: ${e.message}`)
  }
  finally {
    installing.value = null
  }
}

async function onSkillConfirm(data: { name: string, content: string }) {
  try {
    await API.importCustomSkill(data.name, data.content)
    showSkillDialog.value = false
    // Refresh skills list
    API.getMarketItems().then((res) => {
      skills.value = res.items ?? []
    }).catch(() => {})
  }
  catch (e: any) {
    alert(`导入失败: ${e.message}`)
  }
}
</script>

<template>
  <BoxContainer class="text-sm">
    <Accordion :value="accordionValue" class="pb-8" multiple>
      <!-- MCP 工具服务 -->
      <ConfigGroup value="mcp" header="MCP 工具服务">
        <div class="grid gap-3">
          <div v-if="mcpLoading" class="text-white/40 text-xs py-2">
            检查可用性...
          </div>
          <template v-else>
            <div v-for="svc in mcpServices" :key="svc.name" class="skill-item">
              <div class="flex-1 min-w-0">
                <div class="font-bold text-sm text-white">{{ svc.displayName }}</div>
                <div class="text-xs op-50 truncate">{{ svc.description }}</div>
              </div>
              <div class="ml-3 shrink-0">
                <span
                  class="text-xs font-bold"
                  :class="svc.source === 'builtin' ? 'text-green-400' : 'text-blue-400'"
                >
                  {{ svc.source === 'builtin' ? '内置' : '外部' }}
                </span>
              </div>
            </div>
            <div v-if="mcpServices.length === 0" class="text-white/40 text-xs py-2">
              暂无可用 MCP 服务
            </div>
          </template>
          <button class="add-btn" @click="showMcpDialog = true">
            +
          </button>
        </div>
      </ConfigGroup>

      <!-- 技能仓库 -->
      <ConfigGroup value="skills" header="技能仓库">
        <div class="grid gap-3">
          <div v-for="item in skills" :key="item.id" class="skill-item">
            <div class="flex-1 min-w-0">
              <div class="font-bold text-sm text-white">{{ item.title }}</div>
              <div class="text-xs op-50 truncate">{{ item.description }}</div>
            </div>
            <div class="ml-3 shrink-0">
              <span v-if="item.installed" class="text-green-400 text-xs font-bold">已安装</span>
              <button
                v-else-if="installing === item.id"
                class="px-2 py-1 bg-white/10 rounded text-xs op-50 cursor-wait"
                disabled
              >
                安装中...
              </button>
              <button
                v-else
                class="px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-xs transition"
                @click="installItem(item)"
              >
                安装
              </button>
            </div>
          </div>
          <button class="add-btn" @click="showSkillDialog = true">
            +
          </button>
        </div>
      </ConfigGroup>
    </Accordion>

    <!-- Dialogs -->
    <McpAddDialog
      :visible="showMcpDialog"
      @confirm="onMcpConfirm"
      @cancel="showMcpDialog = false"
    />
    <SkillAddDialog
      :visible="showSkillDialog"
      @confirm="onSkillConfirm"
      @cancel="showSkillDialog = false"
    />
  </BoxContainer>
</template>

<style scoped>
.skill-item {
  display: flex;
  align-items: center;
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  transition: background 0.2s;
}

.skill-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0.5rem;
  border: 1px dashed rgba(212, 175, 55, 0.35);
  border-radius: 8px;
  background: transparent;
  color: rgba(212, 175, 55, 0.6);
  font-size: 1.25rem;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}

.add-btn:hover {
  border-color: rgba(212, 175, 55, 0.7);
  color: rgba(212, 175, 55, 1);
  background: rgba(212, 175, 55, 0.06);
}
</style>
