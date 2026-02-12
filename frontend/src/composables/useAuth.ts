import { computed, ref } from 'vue'
import { ACCESS_TOKEN, REFRESH_TOKEN } from '@/api'
import coreApi from '@/api/core'

export const nagaUser = ref<{ username: string, sub?: string } | null>(null)
export const isNagaLoggedIn = computed(() => !!nagaUser.value)

// 防止多个组件调用 useAuth() 时重复 fetchMe
let _initFetched = false

export function useAuth() {
  async function login(username: string, password: string) {
    const res = await coreApi.authLogin(username, password)
    if (res.success) {
      ACCESS_TOKEN.value = res.accessToken
      REFRESH_TOKEN.value = res.refreshToken
      nagaUser.value = res.user
    }
    return res
  }

  async function fetchMe() {
    try {
      const res = await coreApi.authMe()
      if (res.user) {
        nagaUser.value = res.user
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
      ACCESS_TOKEN.value = undefined
      REFRESH_TOKEN.value = undefined
      nagaUser.value = null
    }
  }

  function skipLogin() {
    nagaUser.value = null
  }

  // 首次调用时自动恢复会话
  if (!_initFetched) {
    _initFetched = true
    fetchMe()
  }

  return { login, fetchMe, logout, skipLogin }
}
