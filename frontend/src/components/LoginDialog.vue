<script setup lang="ts">
import { Button, InputText } from 'primevue'
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ success: [], skip: [] }>()

const { login } = useAuth()

const username = ref('')
const password = ref('')
const errorMsg = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await login(username.value, password.value)
    emit('success')
  }
  catch {
    errorMsg.value = '登录失败，请检查用户名和密码'
  }
  finally {
    loading.value = false
  }
}

function handleSkip() {
  emit('skip')
}
</script>

<template>
  <Transition name="login-fade">
    <div v-if="visible" class="login-overlay">
      <div class="login-card">
        <h2 class="login-title">
          Naga 账号登录
        </h2>
        <div class="login-form">
          <InputText
            v-model="username"
            placeholder="用户名"
            class="login-input"
            @keyup.enter="handleLogin"
          />
          <InputText
            v-model="password"
            type="password"
            placeholder="密码"
            class="login-input"
            @keyup.enter="handleLogin"
          />
          <div v-if="errorMsg" class="login-error">
            {{ errorMsg }}
          </div>
          <Button
            label="登 录"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          />
        </div>
        <div class="login-skip" @click="handleSkip">
          不登录，直接进入
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.login-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}

.login-card {
  width: 360px;
  padding: 2rem 2.5rem;
  border: 1px solid rgba(212, 175, 55, 0.5);
  border-radius: 12px;
  background: rgba(20, 14, 6, 0.92);
  box-shadow: 0 0 40px rgba(212, 175, 55, 0.1);
}

.login-title {
  margin: 0 0 1.5rem;
  font-size: 1.25rem;
  font-weight: 600;
  text-align: center;
  color: rgba(212, 175, 55, 0.9);
  letter-spacing: 0.05em;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.login-input {
  width: 100%;
}

.login-error {
  font-size: 0.8rem;
  color: #e85d5d;
  text-align: center;
}

.login-btn {
  width: 100%;
  margin-top: 0.25rem;
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.8), rgba(180, 140, 30, 0.8));
  border: none;
  color: #1a1206;
  font-weight: 600;
}

.login-btn:hover {
  background: linear-gradient(135deg, rgba(212, 175, 55, 1), rgba(180, 140, 30, 1));
}

.login-skip {
  margin-top: 1rem;
  font-size: 0.8rem;
  text-align: center;
  color: rgba(212, 175, 55, 0.45);
  cursor: pointer;
  transition: color 0.2s;
}

.login-skip:hover {
  color: rgba(212, 175, 55, 0.8);
}

.login-fade-enter-active {
  transition: opacity 0.3s ease;
}

.login-fade-enter-from {
  opacity: 0;
}

.login-fade-leave-active {
  transition: opacity 0.3s ease;
}

.login-fade-leave-to {
  opacity: 0;
}
</style>
