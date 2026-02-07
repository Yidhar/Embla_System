<script setup lang="ts">
import type { SelectChangeEvent } from 'primevue'
import { useStorage } from '@vueuse/core'
import { Accordion, Button, InputNumber, InputText, Select, Slider, Textarea } from 'primevue'
import { ref, useTemplateRef } from 'vue'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import ConfigItem from '@/components/ConfigItem.vue'
import { CONFIG, DEFALUT_CONFIG, DEFALUT_MODEL, MODELS } from '@/utils/config'

const selectedModel = ref<keyof typeof MODELS>(DEFALUT_MODEL)
const modelSelectRef = useTemplateRef<{
  updateModel: (event: SelectChangeEvent | null, value: string) => void
}>('modelSelectRef')

function recoverUiConfig() {
  modelSelectRef.value?.updateModel(null, DEFALUT_MODEL)
  CONFIG.value.ui = { ...DEFALUT_CONFIG.ui }
}

function onModelChange(value: keyof typeof MODELS) {
  CONFIG.value.ui.model = { ...MODELS[value] }
}

const accordionValue = useStorage('accordion-config', [])
</script>

<template>
  <BoxContainer class="text-sm">
    <Accordion :value="accordionValue" multiple>
      <ConfigGroup value="system">
        <template #header>
          <div class="flex w-full justify-between">
            <span>系统设置</span>
            <span>v4.0.0</span>
          </div>
        </template>
        <div class="grid gap-4">
          <ConfigItem name="AI 名称" description="修改后将写入 `config.json` 的 `system.ai_name`">
            <InputText id="ai-name" v-model="CONFIG.system.ai_name" />
          </ConfigItem>
          <ConfigItem name="最大 Token 数" description="单次对话的最大长度限制">
            <InputNumber v-model="CONFIG.system.max_tokens" />
          </ConfigItem>
          <ConfigItem name="历史轮数" description="系统会保留最近几轮对话内容作为上下文">
            <InputNumber v-model="CONFIG.system.max_history_rounds" />
          </ConfigItem>
          <ConfigItem name="加载天数" description="从最近几天的日志文件中加载历史对话">
            <InputNumber v-model="CONFIG.system.context_load_days" />
          </ConfigItem>
          <ConfigItem layout="column" name="系统提示词" description="编辑对话风格提示词，影响AI的回复风格和语言特点">
            <Textarea v-model="CONFIG.system.system_prompt" rows="10" class="resize-none" />
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="ui">
        <template #header>
          <div class="w-full flex justify-between items-center -my-1.5">
            <span>UI 风格配置</span>
            <Button size="small" label="恢复默认" @click.stop="recoverUiConfig" />
          </div>
        </template>
        <div class="grid *:h-full gap-4">
          <ConfigItem name="用户昵称" description="聊天窗口显示的用户呢称">
            <InputText v-model="CONFIG.ui.user_name" />
          </ConfigItem>
          <ConfigItem name="Live2D 模型位置">
            <div class="flex flex-col items-center justify-evenly *:w-full">
              <label v-for="direction in ['x', 'y'] as const" :key="direction" class="flex items-center">
                <div class="capitalize w-0 trunce -translate-x-4">{{ direction }}</div>
                <Slider v-model="CONFIG.ui.model[direction]" class="w-full" :min="-2" :max="2" :step="0.005" />
              </label>
            </div>
          </ConfigItem>
          <ConfigItem name="Live2D 模型">
            <Select
              ref="modelSelectRef"
              :options="Object.keys(MODELS)"
              :model-value="selectedModel"
              @change="(event) => onModelChange(event.value)"
            />
          </ConfigItem>
          <ConfigItem name="Live2D 模型缩放">
            <Slider v-model="CONFIG.ui.model.size" :min="0" :max="9000" />
          </ConfigItem>
          <ConfigItem name="Live2D 模型超采样倍数">
            <InputNumber v-model="CONFIG.ui.live2d_ssaa" :min="1" :max="4" show-buttons />
          </ConfigItem>
        </div>
      </ConfigGroup>
      <ConfigGroup value="account" header="账号设置">
        <div class="grid *:h-full gap-4">
          <ConfigItem name="用户名">
            <InputText v-model="CONFIG.naga_portal.username" />
          </ConfigItem>
          <ConfigItem name="用户密码">
            <InputText v-model="CONFIG.naga_portal.password" />
          </ConfigItem>
        </div>
      </ConfigGroup>
    </Accordion>
  </BoxContainer>
</template>
