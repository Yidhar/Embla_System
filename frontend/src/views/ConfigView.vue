<script setup lang="ts">
import { useStorage } from '@vueuse/core'
import {
  Accordion,
  AccordionContent,
  AccordionHeader,
  AccordionPanel,
  Button,
  InputNumber,
  InputText,
} from 'primevue'
import BoxContainer from '@/components/BoxContainer.vue'

const config = useStorage('config', {
  ai_name: '娜迦日达',
  max_tokens: 8192,
})
</script>

<template>
  <BoxContainer>
    <Accordion>
      <AccordionPanel value="system">
        <AccordionHeader>系统配置</AccordionHeader>
        <AccordionContent>
          <div class="card flex flex-col justify-center gap-4 [&_*]:w-full">
            <label>
              Agent 昵称
              <InputText id="ai-name" v-model="config.ai_name" />
            </label>
            <label>
              最大令牌数
              <InputNumber v-model="config.max_tokens" />
            </label>
          </div>
        </AccordionContent>
      </AccordionPanel>
      <AccordionPanel value="ui">
        <AccordionHeader>
          <div class="w-full flex justify-between items-center pr-4">
            <span>UI 配置</span>
            <Button size="small" color="{indigo.500}" label="恢复默认" />
          </div>
        </AccordionHeader>
        <AccordionContent>
          <div class="card flex flex-col justify-center gap-4 [&_*]:w-full">
            <label>
              Agent 昵称
              <InputText id="ai-name" v-model="config.ai_name" />
            </label>
            <label>
              最大令牌数
              <InputNumber v-model="config.max_tokens" />
            </label>
          </div>
        </AccordionContent>
      </AccordionPanel>
    </Accordion>
  </BoxContainer>
</template>

<style scoped>
label {
  width: 100%;
  display: grid;
  grid-template-columns: 1fr 2fr;
  align-items: center;
}
</style>
