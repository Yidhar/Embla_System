import { aiter } from 'iterator-helper'
import { decodeBase64, readerToMessages } from '@/utils'
import { ACCESS_TOKEN, ApiClient } from './index'

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
    const messages = readerToMessages(reader)
    const { value } = await messages.next()
    if (!value?.startsWith('session_id: ')) {
      throw new Error('Failed to get sessionId')
    }
    const sessionId = value.slice(12)
    return {
      sessionId,
      response: aiter(messages).map(decodeBase64),
    }
  }
}

export default new CoreApiClient(8000)
