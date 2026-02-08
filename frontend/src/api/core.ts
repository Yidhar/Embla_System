import type { Config } from '@/utils/config'
import { aiter } from 'iterator-helper'
import { decodeBase64, readerToMessageStream } from '@/utils'
import { ACCESS_TOKEN, ApiClient } from './index'

export class CoreApiClient extends ApiClient {
  health(): Promise<{
    status: 'healthy'
    agentReady: true
    timestamp: string
  }> {
    return this.instance.get('/health')
  }

  // systemInfo() {
  //   return this.instance.get<{
  //     version: '4.0.0' | string
  //     status: 'running'
  //     availableServices: []
  //     apiKeyConfigured: boolean
  //   }>('/system/info').then(res => res.data)
  // }

  systemConfig(): Promise<Config> {
    return this.instance.get<{
      status: 'success'
      config: Config
    }>('/system/config').then(res => res.data.config)
  }

  setSystemConfig(config: Config) {
    return this.instance.post<{
      status: 'success'
      message: string
    }>('/system/config', config).then(res => res.data.message)
  }

  chat(message: string, options?: {
    sessionId?: string
    useSelfGame?: boolean
    skipIntentAnalysis?: boolean
  }) {
    return this.instance.post<{
      status: 'success'
      response: string
      sessionId?: string
    }>('/chat', { message, ...options }).then(res => res.data)
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
}

export default new CoreApiClient(8000)
