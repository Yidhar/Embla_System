<script setup lang="ts">
import { Button, InputText } from 'primevue'
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'

const FORGOT_PASSWORD_URL = 'https://naga.furina.chat/reset-password'

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ success: [], skip: [] }>()

const { login, register } = useAuth()

// 'login' | 'register'
const mode = ref<'login' | 'register'>('login')

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMsg = ref('')
const successMsg = ref('')
const loading = ref(false)

function resetForm() {
  username.value = ''
  password.value = ''
  confirmPassword.value = ''
  errorMsg.value = ''
  successMsg.value = ''
}

function switchToRegister() {
  resetForm()
  mode.value = 'register'
}

function switchToLogin() {
  resetForm()
  mode.value = 'login'
}

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

async function handleRegister() {
  if (!username.value || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  if (password.value !== confirmPassword.value) {
    errorMsg.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    await register(username.value, password.value)
    successMsg.value = '注册成功，请登录'
    // 注册成功后自动切回登录，保留用户名
    const savedUsername = username.value
    switchToLogin()
    username.value = savedUsername
    successMsg.value = '注册成功，请登录'
  }
  catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || '注册失败，请稍后重试'
  }
  finally {
    loading.value = false
  }
}

function handleSkip() {
  emit('skip')
}

function openForgotPassword() {
  window.open(FORGOT_PASSWORD_URL, '_blank')
}
</script>

<template>
  <Transition name="login-fade">
    <div v-if="visible" class="login-overlay">
      <div class="login-card">
        <!-- 登录模式 -->
        <template v-if="mode === 'login'">
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
            <div v-if="successMsg" class="login-success">
              {{ successMsg }}
            </div>
            <Button
              label="登 录"
              :loading="loading"
              class="login-btn"
              @click="handleLogin"
            />
          </div>
          <div class="login-links">
            <span class="login-link" @click="switchToRegister">注册账号</span>
            <span class="login-link" @click="openForgotPassword">忘记密码</span>
          </div>
          <div class="login-skip" @click="handleSkip">
            不登录，直接进入
          </div>
        </template>

        <!-- 注册模式 -->
        <template v-else>
          <h2 class="login-title">
            Naga 账号注册
          </h2>
          <div class="login-form">
            <InputText
              v-model="username"
              placeholder="用户名"
              class="login-input"
              @keyup.enter="handleRegister"
            />
            <InputText
              v-model="password"
              type="password"
              placeholder="密码"
              class="login-input"
              @keyup.enter="handleRegister"
            />
            <InputText
              v-model="confirmPassword"
              type="password"
              placeholder="确认密码"
              class="login-input"
              @keyup.enter="handleRegister"
            />
            <div v-if="errorMsg" class="login-error">
              {{ errorMsg }}
            </div>
            <Button
              label="注 册"
              :loading="loading"
              class="login-btn"
              @click="handleRegister"
            />
          </div>
          <div class="login-links">
            <span class="login-link" @click="switchToLogin">返回登录</span>
            <span class="login-link" @click="openForgotPassword">忘记密码</span>
          </div>
          <div class="login-skip" @click="handleSkip">
            不登录，直接进入
          </div>
        </template>
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

.login-success {
  font-size: 0.8rem;
  color: rgba(120, 200, 120, 0.9);
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

.login-links {
  display: flex;
  justify-content: center;
  gap: 1.5rem;
  margin-top: 1rem;
}

.login-link {
  font-size: 0.8rem;
  color: rgba(212, 175, 55, 0.55);
  cursor: pointer;
  transition: color 0.2s;
}

.login-link:hover {
  color: rgba(212, 175, 55, 0.9);
}

.login-skip {
  margin-top: 0.6rem;
  font-size: 0.8rem;
  text-align: center;
  color: rgba(212, 175, 55, 0.35);
  cursor: pointer;
  transition: color 0.2s;
}

.login-skip:hover {
  color: rgba(212, 175, 55, 0.7);
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
