import { computed, ref } from 'vue'
import { ACCESS_TOKEN } from '@/api'
import { CONFIG } from '@/utils/config'

export const nagaUser = ref<{ username: string, sub?: string } | null>(null)
export const isNagaLoggedIn = computed(() => false)
export const sessionRestored = ref(false)

function applyLocalOnlyDefaults() {
  ACCESS_TOKEN.value = ''
  CONFIG.value.memory_server.token = null
}

applyLocalOnlyDefaults()

export function useAuth() {
  async function login(_username: string, _password: string, _captchaId?: string, _captchaAnswer?: string) {
    applyLocalOnlyDefaults()
    return {
      success: false,
      user: null,
      accessToken: '',
      message: 'Remote authentication is disabled in local-only mode',
    }
  }

  async function register(_username: string, _email: string, _password: string, _verificationCode: string) {
    applyLocalOnlyDefaults()
    return {
      success: false,
      accessToken: undefined as string | undefined,
      user: undefined as { username: string, email: string, sub?: string } | undefined,
      message: 'Remote registration is disabled in local-only mode',
    }
  }

  async function sendVerification(_email: string, _username: string, _captchaId?: string, _captchaAnswer?: string) {
    return {
      success: false,
      message: 'Remote verification is disabled in local-only mode',
    }
  }

  async function getCaptcha() {
    return {
      captchaId: '',
      question: 'Remote captcha is disabled in local-only mode',
    }
  }

  async function fetchMe() {
    applyLocalOnlyDefaults()
    nagaUser.value = null
    sessionRestored.value = false
    return { user: null as null, memoryUrl: undefined as string | undefined }
  }

  async function logout() {
    applyLocalOnlyDefaults()
    nagaUser.value = null
    sessionRestored.value = false
  }

  function skipLogin() {
    applyLocalOnlyDefaults()
    nagaUser.value = null
    sessionRestored.value = false
  }

  return { login, register, sendVerification, getCaptcha, fetchMe, logout, skipLogin }
}
