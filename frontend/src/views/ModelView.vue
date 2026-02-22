<script setup lang="ts">
import { useStorage } from '@vueuse/core'
import { Accordion, Divider, InputNumber, InputText, Select, ToggleSwitch } from 'primevue'
import { computed, ref, watch } from 'vue'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import ConfigItem from '@/components/ConfigItem.vue'
import { isNagaLoggedIn, nagaUser } from '@/composables/useAuth'
import { CONFIG } from '@/utils/config'

const accordionValue = useStorage('accordion-model', ['asr'])

const ASR_PROVIDERS = {
  qwen: 'Qwen',
  openai: 'OpenAI',
  local: 'FunASR',
}

const TTS_VOICES = {
  Cherry: 'Default',
}

const API_PROVIDERS = {
  auto: 'Auto',
  openai_compatible: 'OpenAI Compatible',
  google: 'Google Gemini',
}

const API_PROTOCOLS = {
  auto: 'Auto',
  openai_chat_completions: 'OpenAI Chat Completions',
}

type CodexThinkLevel = 'none' | 'xhigh' | 'high' | 'medium'
type ClaudeThinkLevel = 'placeholder'
type ResolvedApiProtocol = 'openai_chat_completions'

const CODEX_THINK_LEVEL_OPTIONS = {
  none: 'Unset',
  xhigh: 'xhigh',
  high: 'high',
  medium: 'medium',
} as const

const CLAUDE_THINK_OPTIONS = {
  placeholder: 'Placeholder (Not Implemented)',
} as const

const codexThinkLevel = ref<CodexThinkLevel>('none')
const claudeThinkLevel = ref<ClaudeThinkLevel>('placeholder')

function isRecord(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function deepCloneRecord(value: unknown): Record<string, any> {
  if (!isRecord(value)) {
    return {}
  }

  return JSON.parse(JSON.stringify(value))
}

function normalizeCodexThinkLevel(value: unknown): CodexThinkLevel {
  const normalized = String(value ?? '').trim().toLowerCase()
  if (normalized === 'xhigh' || normalized === 'high' || normalized === 'medium') {
    return normalized
  }
  return 'none'
}

function resolveCurrentApiProtocol(): ResolvedApiProtocol {
  return 'openai_chat_completions'
}

const currentApiProtocol = computed<ResolvedApiProtocol>(() => resolveCurrentApiProtocol())
const isOpenaiApiProtocol = computed(() => currentApiProtocol.value === 'openai_chat_completions')
const currentApiProtocolLabel = computed(() => 'OpenAI compatible (openai_chat_completions)')

function applyCodexThinkLevel(level: CodexThinkLevel) {
  const nextHeaders = deepCloneRecord(CONFIG.value.api.extra_headers)
  if (level === 'none') {
    delete nextHeaders.reasoning_effort
  }
  else {
    nextHeaders.reasoning_effort = level
  }
  CONFIG.value.api.extra_headers = nextHeaders
}

function removeLegacyGeminiNativeConfig() {
  const protocol = String(CONFIG.value.api.protocol ?? '').trim().toLowerCase()
  if (protocol === 'google_generate_content' || protocol === 'google' || protocol === 'gemini') {
    CONFIG.value.api.protocol = 'openai_chat_completions'
  }

  CONFIG.value.api.google_live_api = false

  const nextBody = deepCloneRecord(CONFIG.value.api.extra_body)
  const generationConfig = isRecord(nextBody.generationConfig) ? { ...nextBody.generationConfig } : {}

  if (isRecord(generationConfig.thinkingConfig)) {
    delete generationConfig.thinkingConfig
  }

  if (Object.keys(generationConfig).length > 0) {
    nextBody.generationConfig = generationConfig
  }
  else {
    delete nextBody.generationConfig
  }

  delete nextBody.mediaResolution
  CONFIG.value.api.extra_body = nextBody
}

function onCodexThinkLevelChange(value: unknown) {
  codexThinkLevel.value = normalizeCodexThinkLevel(value)
  applyCodexThinkLevel(codexThinkLevel.value)
}

removeLegacyGeminiNativeConfig()

watch(
  () => CONFIG.value.api.protocol,
  (value) => {
    const protocol = String(value ?? '').trim().toLowerCase()
    if (protocol === 'google_generate_content' || protocol === 'google' || protocol === 'gemini') {
      CONFIG.value.api.protocol = 'openai_chat_completions'
    }
  },
)

watch(
  () => CONFIG.value.api.extra_headers,
  (value) => {
    if (!isRecord(value)) {
      codexThinkLevel.value = 'none'
      return
    }
    codexThinkLevel.value = normalizeCodexThinkLevel(value.reasoning_effort)
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <BoxContainer class="text-sm">
    <Accordion :value="accordionValue" class="pb-8" multiple>
      <ConfigGroup value="llm" header="大语言模型">
        <div class="grid gap-4">
          <ConfigItem name="模型名称" description="用于对话的大语言模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.api.model" />
          </ConfigItem>
          <ConfigItem name="API 地址" description="大语言模型的 API 地址">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆 ({{ nagaUser?.username }})，使用 NagaModel 网关</span>
            <InputText v-else v-model="CONFIG.api.base_url" />
          </ConfigItem>
          <ConfigItem name="API 密钥" description="大语言模型的 API 密钥">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆 ({{ nagaUser?.username }})，无需输入</span>
            <InputText v-else v-model="CONFIG.api.api_key" type="password" />
          </ConfigItem>
          <ConfigItem name="API 提供商" description="用于协议自动识别（可选）">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <Select v-else v-model="CONFIG.api.provider" :options="Object.keys(API_PROVIDERS)">
              <template #option="{ option }">
                {{ API_PROVIDERS[option as keyof typeof API_PROVIDERS] }}
              </template>
              <template #value="{ value }">
                {{ API_PROVIDERS[value as keyof typeof API_PROVIDERS] }}
              </template>
            </Select>
          </ConfigItem>
          <ConfigItem name="API 协议" description="建议保持 auto，让系统按地址自动路由">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <Select v-else v-model="CONFIG.api.protocol" :options="Object.keys(API_PROTOCOLS)">
              <template #option="{ option }">
                {{ API_PROTOCOLS[option as keyof typeof API_PROTOCOLS] }}
              </template>
              <template #value="{ value }">
                {{ API_PROTOCOLS[value as keyof typeof API_PROTOCOLS] }}
              </template>
            </Select>
          </ConfigItem>
          <ConfigItem
            name="系统代理"
            description="启用后按系统环境变量（HTTP_PROXY/HTTPS_PROXY）发起模型请求"
          >
            <label class="inline-flex items-center gap-3">
              启用
              <ToggleSwitch v-model="CONFIG.api.applied_proxy" />
            </label>
          </ConfigItem>
          <ConfigItem name="请求超时（秒）" description="模型请求超时时间">
            <InputNumber v-model="CONFIG.api.request_timeout" :min="1" :max="600" show-buttons />
          </ConfigItem>
          <ConfigItem name="当前请求协议" description="按 protocol/base_url/provider 动态判定，思考参数会自动适配">
            <span>{{ currentApiProtocolLabel }}</span>
          </ConfigItem>
          <ConfigItem
            v-if="isOpenaiApiProtocol"
            name="Codex ThinkLevel"
            description="仅 OpenAI 兼容协议生效；写入附加请求头 reasoning_effort（xhigh/high/medium）"
          >
            <Select
              :model-value="codexThinkLevel"
              :options="Object.keys(CODEX_THINK_LEVEL_OPTIONS)"
              @update:model-value="onCodexThinkLevelChange"
            >
              <template #option="{ option }">
                {{ CODEX_THINK_LEVEL_OPTIONS[option as keyof typeof CODEX_THINK_LEVEL_OPTIONS] }}
              </template>
              <template #value="{ value }">
                {{ CODEX_THINK_LEVEL_OPTIONS[value as keyof typeof CODEX_THINK_LEVEL_OPTIONS] }}
              </template>
            </Select>
          </ConfigItem>
          <ConfigItem v-if="isOpenaiApiProtocol" name="Claude Think" description="占位配置，后续接入">
            <Select
              :model-value="claudeThinkLevel"
              :options="Object.keys(CLAUDE_THINK_OPTIONS)"
              disabled
            >
              <template #option="{ option }">
                {{ CLAUDE_THINK_OPTIONS[option as keyof typeof CLAUDE_THINK_OPTIONS] }}
              </template>
              <template #value="{ value }">
                {{ CLAUDE_THINK_OPTIONS[value as keyof typeof CLAUDE_THINK_OPTIONS] }}
              </template>
            </Select>
          </ConfigItem>
          <Divider class="m-1!" />
          <ConfigItem name="最大令牌数" description="单次对话的最大长度限制">
            <InputNumber v-model="CONFIG.api.max_tokens" show-buttons />
          </ConfigItem>
          <ConfigItem name="历史轮数" description="使用最近几轮对话内容作为上下文">
            <InputNumber v-model="CONFIG.api.max_history_rounds" show-buttons />
          </ConfigItem>
          <ConfigItem name="加载天数" description="从最近几天的日志文件中加载历史对话">
            <InputNumber v-model="CONFIG.api.context_load_days" show-buttons />
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="control">
        <template #header>
          <div class="w-full flex justify-between items-center -my-1.5">
            <span>电脑控制模型</span>
            <label class="flex items-center gap-4">
              启用
              <ToggleSwitch v-model="CONFIG.computer_control.enabled" size="small" @click.stop />
            </label>
          </div>
        </template>
        <div class="grid gap-4">
          <ConfigItem name="控制模型" description="用于电脑控制任务的主要模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.computer_control.model" />
          </ConfigItem>
          <ConfigItem name="控制模型 API 地址" description="控制模型的 API 地址">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <InputText v-else v-model="CONFIG.computer_control.model_url" />
          </ConfigItem>
          <ConfigItem name="控制模型 API 密钥" description="控制模型的 API 密钥">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需输入</span>
            <InputText v-else v-model="CONFIG.computer_control.api_key" />
          </ConfigItem>
          <Divider class="m-1!" />
          <ConfigItem name="定位模型" description="用于元素定位和坐标识别的模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.computer_control.grounding_model" />
          </ConfigItem>
          <ConfigItem name="定位模型 API 地址" description="定位模型的 API 地址">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <InputText v-else v-model="CONFIG.computer_control.grounding_url" />
          </ConfigItem>
          <ConfigItem name="定位模型 API 密钥" description="定位模型的 API 密钥">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需输入</span>
            <InputText v-else v-model="CONFIG.computer_control.grounding_api_key" />
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="asr">
        <template #header>
          <div class="w-full flex justify-between items-center -my-1.5">
            <span>语音识别模型</span>
            <label class="flex items-center gap-4">
              启用
              <ToggleSwitch v-model="CONFIG.voice_realtime.enabled" size="small" @click.stop />
            </label>
          </div>
        </template>
        <div class="grid gap-4">
          <ConfigItem name="模型名称" description="用于语音识别的模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.voice_realtime.asr_model" />
          </ConfigItem>
          <template v-if="!isNagaLoggedIn">
            <ConfigItem name="模型提供者" description="语音识别模型的提供者">
              <Select v-model="CONFIG.voice_realtime.provider" :options="Object.keys(ASR_PROVIDERS)">
                <template #option="{ option }">
                  {{ ASR_PROVIDERS[option as keyof typeof ASR_PROVIDERS] }}
                </template>
                <template #value="{ value }">
                  {{ ASR_PROVIDERS[value as keyof typeof ASR_PROVIDERS] }}
                </template>
              </Select>
            </ConfigItem>
            <ConfigItem name="API 密钥" description="语音识别模型的 API 密钥">
              <InputText v-model="CONFIG.voice_realtime.api_key" />
            </ConfigItem>
          </template>
          <ConfigItem v-else name="API 密钥">
            <span class="naga-authed">&#10003; 已登陆，无需输入</span>
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="tts">
        <template #header>
          <div class="w-full flex justify-between items-center -my-1.5">
            <span>语音合成模型</span>
            <label class="flex items-center gap-4">
              启用
              <ToggleSwitch v-model="CONFIG.system.voice_enabled" size="small" @click.stop />
            </label>
          </div>
        </template>
        <div class="grid gap-4">
          <ConfigItem name="模型名称" description="用于语音合成的模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.voice_realtime.tts_model" />
          </ConfigItem>
          <ConfigItem name="声线" description="语音合成模型的声线">
            <Select v-model="CONFIG.tts.default_voice" :options="Object.keys(TTS_VOICES)">
              <template #option="{ option }">
                {{ TTS_VOICES[option as keyof typeof TTS_VOICES] }}
              </template>
              <template #value="{ value }">
                {{ TTS_VOICES[value as keyof typeof TTS_VOICES] }}
              </template>
            </Select>
          </ConfigItem>
          <template v-if="!isNagaLoggedIn">
            <ConfigItem name="服务端口" description="用于语音合成的本地服务端口">
              <InputNumber v-model="CONFIG.tts.port" :min="1000" :max="65535" show-buttons />
            </ConfigItem>
            <ConfigItem name="API 密钥" description="语音合成模型的 API 密钥">
              <InputText v-model="CONFIG.tts.api_key" />
            </ConfigItem>
          </template>
          <ConfigItem v-else name="API 密钥">
            <span class="naga-authed">&#10003; 已登陆，无需输入</span>
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="embedding" header="嵌入模型">
        <div class="grid gap-4">
          <ConfigItem name="模型名称" description="用于向量嵌入的模型">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需填写</span>
            <InputText v-else v-model="CONFIG.embedding.model" />
          </ConfigItem>
          <ConfigItem name="API 地址" description="嵌入模型的 API 地址（留空使用主模型地址）">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <InputText v-else v-model="CONFIG.embedding.api_base" />
          </ConfigItem>
          <ConfigItem name="API 密钥" description="嵌入模型的 API 密钥（留空使用主模型密钥）">
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，无需输入</span>
            <InputText v-else v-model="CONFIG.embedding.api_key" type="password" />
          </ConfigItem>
        </div>
      </ConfigGroup>
    </Accordion>
  </BoxContainer>
</template>

<style scoped>
.naga-authed {
  color: #4ade80;
  font-size: 0.875rem;
  font-weight: 500;
}
</style>
