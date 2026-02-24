<script setup lang="ts">
import type { CodexMcpSetupResponse, McpRuntimeSnapshot, McpTaskSnapshot } from '@/api/core'
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

type McpConsistency = 'aligned' | 'mismatch' | 'unknown'

interface McpServiceRow extends McpService {
  runtimeStatus: string
  runtimeOnline: boolean
  runtimeSource: string
  consistency: McpConsistency
}

const accordionValue = useStorage('accordion-skill', ['mcp', 'skills'])

// ── MCP 服务 ──
const mcpServices = ref<McpServiceRow[]>([])
const mcpRuntime = ref<McpRuntimeSnapshot | null>(null)
const mcpLoading = ref(true)
const mcpRuntimeError = ref('')
const showMcpDialog = ref(false)
const codexSetupLoading = ref(false)
const codexSetupError = ref('')
const codexSetupResult = ref<CodexMcpSetupResponse | null>(null)
const mcpImportError = ref('')

const mcpSummary = computed(() => {
  const runtime = mcpRuntime.value
  if (!runtime) {
    return null
  }
  return {
    server: runtime.server,
    total: runtime.tasks.total,
    active: runtime.tasks.active,
    completed: runtime.tasks.completed,
    failed: runtime.tasks.failed,
    updatedAt: runtime.timestamp,
  }
})

const codexConnected = computed(() => {
  return mcpServices.value.some((svc) => {
    const name = String(svc.name ?? '').toLowerCase()
    return (name === 'codex-cli' || name === 'codex-mcp') && svc.runtimeOnline
  })
})

function resolveRuntimeStatus(
  service: McpService,
  taskMap: Map<string, McpTaskSnapshot>,
  runtime: McpRuntimeSnapshot | null,
): { status: string, source: string, online: boolean } {
  const task = taskMap.get(service.name)
  if (task) {
    const status = String(task.status || '')
    return {
      status: status || 'unknown',
      source: String(task.source || service.source || ''),
      online: status !== 'unavailable' && status !== 'missing',
    }
  }

  const builtinSet = new Set(runtime?.registry?.serviceNames || [])
  const externalSet = new Set(runtime?.registry?.externalServiceNames || [])
  if (service.source === 'builtin') {
    const online = builtinSet.has(service.name)
    return {
      status: online ? 'registered' : 'unavailable',
      source: 'builtin',
      online,
    }
  }
  const online = externalSet.has(service.name)
  return {
    status: online ? 'configured' : 'unavailable',
    source: 'mcporter',
    online,
  }
}

function mergeMcpServiceRows(
  services: McpService[],
  runtime: McpRuntimeSnapshot | null,
  tasks: McpTaskSnapshot[],
): McpServiceRow[] {
  const taskMap = new Map<string, McpTaskSnapshot>(
    tasks.map(task => [String(task.serviceName || ''), task]),
  )

  return services.map((service) => {
    const runtimeState = resolveRuntimeStatus(service, taskMap, runtime)
    const consistency: McpConsistency = runtime
      ? (service.available === runtimeState.online ? 'aligned' : 'mismatch')
      : 'unknown'
    return {
      ...service,
      runtimeStatus: runtimeState.status,
      runtimeOnline: runtimeState.online,
      runtimeSource: runtimeState.source,
      consistency,
    }
  })
}

function statusLabel(status: string): string {
  const key = String(status || '').toLowerCase()
  const labels: Record<string, string> = {
    registered: '已注册',
    configured: '已配置',
    unavailable: '不可用',
    running: '运行中',
    failed: '失败',
  }
  return labels[key] || (status || 'unknown')
}

async function loadMcpServices() {
  mcpLoading.value = true
  mcpRuntimeError.value = ''
  try {
    const [servicesRes, runtimeRes, taskRes] = await Promise.all([
      API.getMcpServices(),
      API.getMcpStatus(),
      API.getMcpTasks(),
    ])
    const services = (servicesRes.services ?? []) as McpService[]
    const tasks = (taskRes.tasks ?? []) as McpTaskSnapshot[]

    mcpRuntime.value = runtimeRes
    mcpServices.value = mergeMcpServiceRows(services, runtimeRes, tasks)
  }
  catch (error: any) {
    mcpRuntime.value = null
    mcpRuntimeError.value = `MCP 状态拉取失败: ${extractErrorMessage(error)}`
    try {
      const res = await API.getMcpServices()
      const fallbackServices = (res.services ?? []) as McpService[]
      mcpServices.value = mergeMcpServiceRows(fallbackServices, null, [])
    }
    catch {
      mcpServices.value = []
    }
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

function refreshMcpRuntime() {
  void loadMcpServices()
}

async function onMcpConfirm(data: { name: string, config: Record<string, any> }) {
  mcpImportError.value = ''
  try {
    await API.importMcpConfig(data.name, data.config)
    showMcpDialog.value = false
    await loadMcpServices()
  }
  catch (e: any) {
    mcpImportError.value = `导入失败: ${extractErrorMessage(e)}`
  }
}

// ── 技能管理 ──
const showSkillDialog = ref(false)
const skillImportError = ref('')

async function onSkillConfirm(data: { name: string, content: string }) {
  skillImportError.value = ''
  try {
    await API.importCustomSkill(data.name, data.content)
    showSkillDialog.value = false
  }
  catch (e: any) {
    skillImportError.value = `导入失败: ${extractErrorMessage(e)}`
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
              <button class="setup-btn setup-btn-ghost" :disabled="mcpLoading" @click="refreshMcpRuntime">
                {{ mcpLoading ? '刷新中...' : '刷新状态' }}
              </button>
              <button class="setup-btn" :disabled="codexSetupLoading" @click="setupCodexMcp">
                {{ codexSetupLoading ? '接入中...' : (codexConnected ? '重新接入' : '一键接入') }}
              </button>
            </div>
          </div>

          <div v-if="codexSetupError" class="setup-error">
            {{ codexSetupError }}
          </div>
          <div v-if="mcpImportError" class="setup-error">
            {{ mcpImportError }}
          </div>
          <div v-if="codexSetupResult" class="setup-result">
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

          <div v-if="mcpSummary" class="runtime-summary">
            <div class="setup-line">
              运行态: {{ mcpSummary.server === 'online' ? '在线' : '离线' }}
            </div>
            <div class="setup-line">
              服务总数: {{ mcpSummary.total }}（活跃 {{ mcpSummary.active }} / 内置 {{ mcpSummary.completed }} / 失败 {{ mcpSummary.failed }}）
            </div>
            <div class="setup-line text-white/50">
              更新时间: {{ mcpSummary.updatedAt }}
            </div>
          </div>
          <div v-else-if="mcpRuntimeError" class="setup-warning">
            {{ mcpRuntimeError }}
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
                <span class="ml-2 text-xs font-bold" :class="svc.runtimeOnline ? 'text-green-300' : 'text-red-300'">
                  {{ statusLabel(svc.runtimeStatus) }}
                </span>
                <span
                  v-if="svc.consistency === 'mismatch'"
                  class="ml-2 text-amber-300 text-xs"
                  title="服务可用性与运行态快照不一致"
                >
                  漂移
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

      <!-- 技能管理 -->
      <ConfigGroup value="skills" header="技能管理">
        <div class="grid gap-3">
          <div class="skill-item">
            <div class="flex-1 min-w-0">
              <div class="font-bold text-sm text-white">本地自定义技能</div>
              <div class="text-xs op-50">
                通过右下角按钮导入自定义 `SKILL.md` 内容，写入本地 skills 目录。
              </div>
            </div>
          </div>
          <button class="add-btn" @click="showSkillDialog = true">
            +
          </button>
          <div v-if="skillImportError" class="setup-error">
            {{ skillImportError }}
          </div>
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

.runtime-summary {
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  background: rgba(64, 158, 255, 0.06);
  border: 1px solid rgba(64, 158, 255, 0.28);
  color: rgba(220, 238, 255, 0.95);
  font-size: 0.75rem;
  display: grid;
  gap: 0.2rem;
}

.setup-btn-ghost {
  border-color: rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

.setup-btn-ghost:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.12);
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
