import { ref } from 'vue'
import { CONFIG } from '@/utils/config'

// NagaBusiness 统一网关地址（与 naga_auth.py BUSINESS_URL 保持一致）
const UPDATE_BASE_URL = 'http://62.234.131.204:30031'
// TODO: 在 NagaBusiness 管理后台创建应用后填入实际 APP_ID
const APP_ID = '00000000-0000-0000-0000-000000000000'

export interface UpdateInfo {
  hasUpdate: boolean
  latestVersion: string
  description: string
  forceUpdate: boolean
  /** null 表示当前平台无可用资源 */
  downloadUrl: string | null
  fileSize: number | null
}

function detectPlatform(): string {
  const p = window.electronAPI?.platform
  if (p === 'darwin') return 'macos'
  if (p === 'win32') return 'windows'
  if (p === 'linux') return 'linux'
  // web 环境做粗略猜测
  const ua = navigator.userAgent.toLowerCase()
  if (ua.includes('mac')) return 'macos'
  if (ua.includes('win')) return 'windows'
  return 'linux'
}

export const updateInfo = ref<UpdateInfo | null>(null)
export const showUpdateDialog = ref(false)

export async function checkForUpdate(): Promise<void> {
  try {
    const platform = detectPlatform()
    const url = `${UPDATE_BASE_URL}/api/app/${APP_ID}/latest?platform=${platform}`
    const res = await fetch(url, { signal: AbortSignal.timeout(10_000) })

    if (!res.ok) {
      // 404 = 应用不存在或无可用版本，静默忽略
      if (res.status === 404) return
      return
    }

    const data = await res.json() as {
      version: string
      description: string
      force_update: boolean
      download_url: string | null
      file_size: number | null
    }

    const currentVersion = CONFIG.value.system.version ?? '4.0'
    if (data.version === currentVersion) return

    updateInfo.value = {
      hasUpdate: true,
      latestVersion: data.version,
      description: data.description,
      forceUpdate: data.force_update,
      downloadUrl: data.download_url ? `${UPDATE_BASE_URL}${data.download_url}` : null,
      fileSize: data.file_size,
    }
    showUpdateDialog.value = true
  }
  catch (err) {
    console.warn('[VersionCheck] Failed to check for updates:', err)
  }
}

export function dismissUpdate(): void {
  showUpdateDialog.value = false
}

export function openDownloadUrl(url: string): void {
  window.open(url, '_blank')
}
