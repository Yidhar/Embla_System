<script setup lang="ts">
import type { CodexMcpSetupResponse, MarketItem } from '@/api/core'
import { useStorage } from '@vueuse/core'
import { Accordion } from 'primevue'
import { computed, ref } from 'vue'
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
const codexSetupLoading = ref(false)
const codexSetupError = ref('')
const codexSetupResult = ref<CodexMcpSetupResponse | null>(null)

const codexConnected = computed(() => {
  return mcpServices.value.some((svc) => {
    const name = String(svc.name ?? '').toLowerCase()
    return name === 'codex-cli' || name === 'codex-mcp'
  })
})

async function loadMcpServices() {
  mcpLoading.value = true
  try {
    const res = await API.getMcpServices()
    mcpServices.value = (res.services ?? []).filter(s => s.available)
  }
  catch {
    mcpServices.value = []
  }
  finally {
    mcpLoading.value = false
  }
}
void loadMcpServices()

function extractErrorMessage(error: any) {
  return error?.response?.data?.detail ?? error?.message ?? '未知错误'
}

async function setupCodexMcp() {
  codexSetupLoading.value = true
  codexSetupError.value = ''
  try {
    codexSetupResult.value = await API.setupCodexMcp({
      serverName: 'codex-cli',
      installMode: 'npx',
      writeCompatAliases: true,
      forceOverwrite: true,
      validateConnection: true,
      validateWithAskCodex: false,
      timeoutSeconds: 120,
    })
    await loadMcpServices()
  }
  catch (error: any) {
    codexSetupError.value = `Codex MCP 接入失败: ${extractErrorMessage(error)}`
  }
  finally {
    codexSetupLoading.value = false
  }
}

async function onMcpConfirm(data: { name: string, config: Record<string, any> }) {
  try {
    await API.importMcpConfig(data.name, data.config)
    showMcpDialog.value = false
    await loadMcpServices()
  }
  catch (e: any) {
    alert(`导入失败: ${extractErrorMessage(e)}`)
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
          <div class="codex-setup-card">
            <div class="flex-1 min-w-0">
              <div class="font-bold text-sm text-white">
                Codex MCP 一键接入
              </div>
              <div class="text-xs op-60">
                自动写入 mcporter 配置并做 ping 连通性检查（服务名：codex-cli）。
              </div>
            </div>
            <div class="ml-3 shrink-0 flex items-center gap-2">
              <span v-if="codexConnected" class="text-green-400 text-xs font-bold">已接入</span>
              <button class="setup-btn" :disabled="codexSetupLoading" @click="setupCodexMcp">
                {{ codexSetupLoading ? '接入中...' : (codexConnected ? '重新接入' : '一键接入') }}
              </button>
            </div>
          </div>

          <div v-if="codexSetupError" class="setup-error">
            {{ codexSetupError }}
          </div>
          <div v-else-if="codexSetupResult" class="setup-result">
            <div class="setup-line">
              状态: {{ codexSetupResult.status }}
            </div>
            <div class="setup-line">
              写入服务: {{ codexSetupResult.writtenServers?.join(', ') || '无' }}
            </div>
            <div class="setup-line">
              Ping 校验: {{ codexSetupResult.validation?.ping?.ok ? '通过' : '失败' }}
            </div>
            <div class="setup-line text-white/50">
              配置路径: {{ codexSetupResult.configPath }}
            </div>
            <div v-if="codexSetupResult.warnings?.length" class="setup-warning">
              {{ codexSetupResult.warnings.join(' | ') }}
            </div>
          </div>

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

.codex-setup-card {
  display: flex;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid rgba(60, 167, 255, 0.35);
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(60, 167, 255, 0.08), rgba(60, 167, 255, 0.03));
}

.setup-btn {
  padding: 0.35rem 0.6rem;
  border: 1px solid rgba(60, 167, 255, 0.55);
  border-radius: 6px;
  background: rgba(60, 167, 255, 0.12);
  color: rgba(180, 225, 255, 1);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.setup-btn:hover:not(:disabled) {
  background: rgba(60, 167, 255, 0.2);
  border-color: rgba(90, 185, 255, 0.9);
}

.setup-btn:disabled {
  cursor: wait;
  opacity: 0.6;
}

.setup-error {
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  background: rgba(232, 93, 93, 0.1);
  border: 1px solid rgba(232, 93, 93, 0.35);
  color: #ffb1b1;
  font-size: 0.75rem;
}

.setup-result {
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.75rem;
  display: grid;
  gap: 0.2rem;
}

.setup-line {
  word-break: break-all;
}

.setup-warning {
  color: #ffcd6d;
  margin-top: 0.15rem;
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
