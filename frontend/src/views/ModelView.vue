<script setup lang="ts">
import { useStorage } from '@vueuse/core'
import { Accordion, Divider, InputText } from 'primevue'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import ConfigItem from '@/components/ConfigItem.vue'
import { CONFIG } from '@/utils/config'

const accordionValue = useStorage('accordion-model', ['api'])
</script>

<template>
  <BoxContainer class="text-sm">
    <Accordion :value="accordionValue" multiple>
      <ConfigGroup value="api" header="API 设置">
        <div class="grid gap-4">
          <ConfigItem name="LLM 模型" description="选择用于对话的 LLM 模型">
            <InputText v-model="CONFIG.api.model" />
          </ConfigItem>
          <ConfigItem name="LLM API 地址" description="LLM 模型的 API 地址">
            <InputText v-model="CONFIG.api.base_url" />
          </ConfigItem>
          <ConfigItem name="LLM API 密钥" description="用于连接 API 的密钥">
            <InputText v-model="CONFIG.api.api_key" />
          </ConfigItem>
          <Divider class="m-1!" />
          <ConfigItem name="电脑控制模型" description="用于电脑控制任务的主要模型">
            <InputText v-model="CONFIG.computer_control.model" />
          </ConfigItem>
          <ConfigItem name="电脑控制 API 地址" description="电脑控制模型的 API 地址">
            <InputText v-model="CONFIG.computer_control.model_url" />
          </ConfigItem>
          <ConfigItem name="电脑控制 API 密钥" description="电脑控制模型的 API 密钥">
            <InputText v-model="CONFIG.computer_control.api_key" />
          </ConfigItem>
          <Divider class="m-1!" />
          <ConfigItem name="定位模型" description="用于元素定位和坐标识别的模型">
            <InputText v-model="CONFIG.computer_control.grounding_model" />
          </ConfigItem>
          <ConfigItem name="定位模型 API 地址" description="定位模型的 API 地址">
            <InputText v-model="CONFIG.computer_control.grounding_url" />
          </ConfigItem>
          <ConfigItem name="定位模型 API 密钥" description="定位模型的 API 密钥">
            <InputText v-model="CONFIG.computer_control.grounding_api_key" />
          </ConfigItem>
        </div>
      </ConfigGroup>
    </Accordion>
  </BoxContainer>
</template>
