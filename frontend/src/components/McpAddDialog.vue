<script setup lang="ts">
import { Button, InputText, Textarea } from 'primevue'
import { computed, ref } from 'vue'

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ confirm: [data: { name: string, config: Record<string, any> }], cancel: [] }>()

const name = ref('')
const jsonText = ref('')
const errorMsg = ref('')

const canSubmit = computed(() => name.value.trim() && jsonText.value.trim())

function handleConfirm() {
  if (!name.value.trim()) {
    errorMsg.value = '请输入服务名称'
    return
  }
  if (!jsonText.value.trim()) {
    errorMsg.value = '请输入 MCP 配置 JSON'
    return
  }
  try {
    const config = JSON.parse(jsonText.value)
    emit('confirm', { name: name.value.trim(), config })
  }
  catch {
    errorMsg.value = 'JSON 格式无效'
    return
  }
  errorMsg.value = ''
}

function handleCancel() {
  name.value = ''
  jsonText.value = ''
  errorMsg.value = ''
  emit('cancel')
}
</script>

<template>
  <Transition name="dialog-fade">
    <div v-if="visible" class="dialog-overlay" @click.self="handleCancel">
      <div class="dialog-card">
        <h2 class="dialog-title">
          导入 MCP 工具服务
        </h2>
        <div class="dialog-form">
          <label class="dialog-label">服务名称</label>
          <InputText
            v-model="name"
            placeholder="服务名称（如 my-mcp-tool）"
            class="dialog-input"
          />

          <label class="dialog-label">MCP 配置 JSON</label>
          <Textarea
            v-model="jsonText"
            rows="6"
            placeholder='{"command":"npx","args":["-y","@mcp/server"],"type":"stdio"}'
            class="dialog-input resize-none font-mono text-xs!"
          />

          <div v-if="errorMsg" class="dialog-error">
            {{ errorMsg }}
          </div>
          <Button
            label="确认导入"
            :disabled="!canSubmit"
            class="dialog-btn"
            @click="handleConfirm"
          />
        </div>
        <div class="dialog-skip" @click="handleCancel">
          取消
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(6px);
}

.dialog-card {
  position: relative;
  z-index: 10000;
  width: 400px;
  max-height: 85vh;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  border: 1px solid rgba(212, 175, 55, 0.5);
  border-radius: 12px;
  background: rgba(20, 14, 6, 0.98);
  box-shadow: 0 0 60px rgba(0, 0, 0, 0.5), 0 0 40px rgba(212, 175, 55, 0.1);
}

.dialog-title {
  margin: 0 0 1.5rem;
  font-size: 1.25rem;
  font-weight: 600;
  text-align: center;
  color: rgba(212, 175, 55, 0.9);
  letter-spacing: 0.05em;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.dialog-label {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
}

.dialog-input {
  width: 100%;
}

.dialog-error {
  font-size: 0.8rem;
  color: #e85d5d;
  text-align: center;
}

.dialog-btn {
  width: 100%;
  margin-top: 0.25rem;
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.8), rgba(180, 140, 30, 0.8));
  border: none;
  color: #1a1206;
  font-weight: 600;
}

.dialog-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(212, 175, 55, 1), rgba(180, 140, 30, 1));
}

.dialog-skip {
  margin-top: 1rem;
  font-size: 0.8rem;
  text-align: center;
  color: rgba(212, 175, 55, 0.45);
  cursor: pointer;
  transition: color 0.2s;
}

.dialog-skip:hover {
  color: rgba(212, 175, 55, 0.8);
}

.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.3s ease;
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}
</style>
