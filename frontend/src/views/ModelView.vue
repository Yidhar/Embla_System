<script setup lang="ts">
import { useStorage } from '@vueuse/core'
import { Accordion, Divider, InputNumber, InputText, Select, Textarea, ToggleSwitch } from 'primevue'
import { ref, watch } from 'vue'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import ConfigItem from '@/components/ConfigItem.vue'
import { isNagaLoggedIn, nagaUser } from '@/composables/useAuth'
import { CONFIG } from '@/utils/config'

const accordionValue = useStorage('accordion-model', ['asr'])

const ASR_PROVIDERS = {
  qwen: '通义千问',
  openai: 'OpenAI',
  local: 'FunASR',
}

const TTS_VOICES = {
  Cherry: '默认',
}

const API_PROVIDERS = {
  auto: '自动识别',
  openai_compatible: 'OpenAI 兼容',
  google: 'Google Gemini',
}

const API_PROTOCOLS = {
  auto: '自动识别',
  openai_chat_completions: 'OpenAI Chat Completions',
  google_generate_content: 'Google Generate Content',
}

const apiExtraHeadersText = ref('{}')
const apiExtraBodyText = ref('{}')
const apiExtraHeadersError = ref('')
const apiExtraBodyError = ref('')

function prettyJson(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return '{}'
  }
  try {
    return JSON.stringify(value, null, 2)
  }
  catch {
    return '{}'
  }
}

watch(
  () => CONFIG.value.api.extra_headers,
  (value) => {
    apiExtraHeadersText.value = prettyJson(value)
  },
  { immediate: true, deep: true },
)

watch(
  () => CONFIG.value.api.extra_body,
  (value) => {
    apiExtraBodyText.value = prettyJson(value)
  },
  { immediate: true, deep: true },
)

function applyApiJson(field: 'extra_headers' | 'extra_body', rawText: string) {
  const text = (rawText || '').trim()
  const errorRef = field === 'extra_headers' ? apiExtraHeadersError : apiExtraBodyError

  if (!text) {
    CONFIG.value.api[field] = {}
    errorRef.value = ''
    if (field === 'extra_headers') {
      apiExtraHeadersText.value = '{}'
    }
    else {
      apiExtraBodyText.value = '{}'
    }
    return
  }

  try {
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      errorRef.value = '请输入 JSON 对象，例如 {"x-foo":"bar"}'
      return
    }

    CONFIG.value.api[field] = parsed
    errorRef.value = ''
    const pretty = JSON.stringify(parsed, null, 2)
    if (field === 'extra_headers') {
      apiExtraHeadersText.value = pretty
    }
    else {
      apiExtraBodyText.value = pretty
    }
  }
  catch {
    errorRef.value = 'JSON 格式无效，请检查引号和逗号'
  }
}
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
            name="Google Live API"
            description="启用后 Google 流式对话使用 BidiGenerateContent（WebSocket）"
          >
            <span v-if="isNagaLoggedIn" class="naga-authed">&#10003; 已登陆，使用 NagaModel 网关</span>
            <label v-else class="inline-flex items-center gap-3">
              启用
              <ToggleSwitch v-model="CONFIG.api.google_live_api" />
            </label>
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
          <ConfigItem name="附加请求头（JSON）" description="例如 {&quot;x-trace-id&quot;:&quot;demo&quot;}">
            <Textarea
              v-model="apiExtraHeadersText"
              rows="4"
              class="w-full font-mono text-xs"
              @blur="applyApiJson('extra_headers', apiExtraHeadersText)"
            />
            <small v-if="apiExtraHeadersError" class="config-error">{{ apiExtraHeadersError }}</small>
          </ConfigItem>
          <ConfigItem name="附加请求体（JSON）" description="例如 {&quot;candidateCount&quot;:1}">
            <Textarea
              v-model="apiExtraBodyText"
              rows="4"
              class="w-full font-mono text-xs"
              @blur="applyApiJson('extra_body', apiExtraBodyText)"
            />
            <small v-if="apiExtraBodyError" class="config-error">{{ apiExtraBodyError }}</small>
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

.config-error {
  color: #f87171;
  font-size: 0.75rem;
}
</style>
