import { computed, ref, watch } from 'vue'
import { ACCESS_TOKEN, REFRESH_TOKEN } from '@/api'
import coreApi from '@/api/core'
import { CONFIG, backendConnected } from '@/utils/config'

export const nagaUser = ref<{ username: string, sub?: string } | null>(null)
export const isNagaLoggedIn = computed(() => !!nagaUser.value)
export const sessionRestored = ref(false)

// 防止多个组件调用 useAuth() 时重复 fetchMe
let _initFetched = false

/**
 * 同步 memory_server 配置：登录时启用云端记忆，登出时回退到本地
 */
function syncMemoryServer(enabled: boolean, memoryUrl?: string) {
  CONFIG.value.memory_server.enabled = enabled
  CONFIG.value.memory_server.token = enabled ? ACCESS_TOKEN.value : null
  if (enabled && memoryUrl) {
    CONFIG.value.memory_server.url = memoryUrl
  }
}

// Token 刷新时自动同步到 memory_server.token
watch(ACCESS_TOKEN, (newToken) => {
  if (nagaUser.value && CONFIG.value.memory_server.enabled) {
    CONFIG.value.memory_server.token = newToken || null
  }
})

export function useAuth() {
  async function login(username: string, password: string) {
    const res = await coreApi.authLogin(username, password)
    if (res.success) {
      ACCESS_TOKEN.value = res.accessToken
      REFRESH_TOKEN.value = res.refreshToken
      nagaUser.value = res.user
      syncMemoryServer(true, res.memoryUrl)
    }
    return res
  }

  async function register(username: string, email: string, password: string, verificationCode: string) {
    const res = await coreApi.authRegister(username, email, password, verificationCode)
    if (res.success && res.accessToken) {
      ACCESS_TOKEN.value = res.accessToken
      REFRESH_TOKEN.value = res.refreshToken
      nagaUser.value = res.user || null
      syncMemoryServer(true)
    }
    return res
  }

  async function sendVerification(email: string, username: string) {
    return await coreApi.authSendVerification(email, username)
  }

  async function fetchMe() {
    try {
      const res = await coreApi.authMe()
      if (res.user) {
        nagaUser.value = res.user
        sessionRestored.value = true
        syncMemoryServer(true, res.memoryUrl)

        // 防止 fetchMe 在 connectBackend 之前完成导致 CONFIG 被覆盖
        if (!backendConnected.value) {
          const stop = watch(backendConnected, (connected) => {
            if (connected) {
              syncMemoryServer(true, res.memoryUrl)
              stop()
            }
          })
        }
      }
    }
    catch {
      nagaUser.value = null
    }
  }

  async function logout() {
    try {
      await coreApi.authLogout()
    }
    finally {
      ACCESS_TOKEN.value = ''
      REFRESH_TOKEN.value = ''
      nagaUser.value = null
      syncMemoryServer(false)
    }
  }

  function skipLogin() {
    nagaUser.value = null
  }

  // 首次调用时自动恢复会话（仅在有 token 时才请求，避免无谓的 401）
  if (!_initFetched) {
    _initFetched = true
    if (ACCESS_TOKEN.value) {
      fetchMe()
    }
  }

  return { login, register, sendVerification, fetchMe, logout, skipLogin }
}
