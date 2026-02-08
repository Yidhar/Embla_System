import type { Config } from '@/utils/config'
import { aiter } from 'iterator-helper'
import { decodeBase64, readerToMessageStream } from '@/utils/encoding'
import { ACCESS_TOKEN, ApiClient } from './index'

export interface OpenClawStatus {
  found: boolean
  version?: string
  skills_dir: string
  config_path: string
  skills_error?: string
}

export interface MarketItem {
  id: string
  title: string
  description: string
  skill_name: string
  enabled: boolean
  installed: boolean
  eligible?: boolean
  disabled?: boolean
  missing?: boolean
  skill_path: string
  openclaw_visible: boolean
  install_type: string
}

export class CoreApiClient extends ApiClient {
  health(): Promise<{
    status: 'healthy'
    agentReady: true
    timestamp: string
  }> {
    return this.instance.get('/health')
  }

  systemInfo(): Promise<{
    version: '4.0.0' | string
    status: 'running'
    availableServices: []
    apiKeyConfigured: boolean
  }> {
    return this.instance.get('/system/info')
  }

  systemConfig(): Promise<{
    status: 'success'
    config: Config
  }> {
    return this.instance('/system/config')
  }

  setSystemConfig(config: Config): Promise<{
    status: 'success'
    message: string
  }> {
    return this.instance.post('/system/config', config)
  }

  chat(message: string, options?: {
    sessionId?: string
    useSelfGame?: boolean
    skipIntentAnalysis?: boolean
  }): Promise<{
    status: 'success'
    response: string
    sessionId?: string
  }> {
    return this.instance.post('/chat', { message, ...options })
  }

  async chatStream(message: string, options?: {
    sessionId?: string
    returnAudio?: boolean
    disableTTS?: boolean
    skipIntentAnalysis?: boolean
  }): Promise<{
    sessionId?: string
    response: AsyncGenerator<string>
  }> {
    const { body } = await fetch(`${this.endpoint}/chat/stream`, {
      method: 'POST',
      headers: {
        'Accept': 'text/event-stream',
        'Authorization': ACCESS_TOKEN.value ? `Bearer ${ACCESS_TOKEN.value}` : '',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message, ...options }),
    })

    const reader = await body?.getReader()
    if (!reader) {
      throw new Error('Failed to get reader')
    }
    const messageStream = readerToMessageStream(reader)
    const { value } = await messageStream.next()
    if (!value?.startsWith('session_id: ')) {
      throw new Error('Failed to get sessionId')
    }
    return {
      sessionId: value.slice(12),
      response: aiter(messageStream).map(decodeBase64),
    }
  }

  getMarketItems(): Promise<{
    status: 'success'
    openclaw: OpenClawStatus
    items: MarketItem[]
  }> {
    return this.instance.get('/market/items')
  }

  installMarketItem(itemId: string): Promise<{
    status: 'success'
    message: string
    item: MarketItem
    openclaw: OpenClawStatus
  }> {
    return this.instance.post(`/market/items/${itemId}/install`)
  }
}

export default new CoreApiClient(8000)
