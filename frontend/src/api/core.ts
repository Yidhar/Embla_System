import type { Config } from '@/utils/config'
import type { StreamChunk } from '@/utils'
import { aiter } from 'iterator-helper'
import { decodeStreamChunk, readerToMessageStream } from '@/utils'
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
    response: AsyncGenerator<StreamChunk>
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
      response: aiter(messageStream).map(decodeStreamChunk),
    }
  }

  getSessions(): Promise<{
    status: string
    sessions: Array<{
      sessionId: string
      createdAt: string
      lastActiveAt: string
      conversationRounds: number
    }>
    totalSessions: number
  }> {
    return this.instance.get('/sessions').then(res => res.data)
  }

  getSessionDetail(id: string): Promise<{
    status: string
    sessionId: string
    messages: Array<{ role: string; content: string }>
    conversationRounds: number
  }> {
    return this.instance.get(`/sessions/${id}`).then(res => res.data)
  }

  deleteSession(id: string) {
    return this.instance.delete(`/sessions/${id}`).then(res => res.data)
  }

  clearAllSessions() {
    return this.instance.delete('/sessions').then(res => res.data)
  }

  getToolStatus(): Promise<{ message: string; visible: boolean }> {
    return this.instance.get('/tool_status').then(res => res.data)
  }

  getClawdbotReplies(): Promise<{ replies: string[] }> {
    return this.instance.get('/clawdbot/replies').then(res => res.data)
  }

  uploadDocument(file: File, description?: string) {
    const formData = new FormData()
    formData.append('file', file)
    if (description) {
      formData.append('description', description)
    }
    return this.instance.post('/upload/document', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    }).then(res => res.data)
  }

  getMemoryStats() {
    return this.instance.get('/memory/stats').then(res => res.data)
  }

  getQuintuples(): Promise<{
    status: string
    quintuples: Array<{
      subject: string
      subjectType: string
      predicate: string
      object: string
      objectType: string
    }>
    count: number
  }> {
    return this.instance.get('/memory/quintuples').then(res => res.data)
  }

  searchQuintuples(keywords: string): Promise<{
    status: string
    quintuples: Array<{
      subject: string
      subjectType: string
      predicate: string
      object: string
      objectType: string
    }>
    count: number
  }> {
    return this.instance.get(`/memory/quintuples/search?keywords=${encodeURIComponent(keywords)}`).then(res => res.data)
  }

  getMarketItems(): Promise<{
    status: string
    openclaw: {
      found: boolean
      version: string | null
      skillsDir: string
      configPath: string
      skillsError: string | null
    }
    items: Array<{
      id: string
      title: string
      description: string
      skillName: string
      installed: boolean
      enabled: boolean
      installType: string
    }>
  }> {
    return this.instance.get('/openclaw/market/items').then(res => res.data)
  }

  installMarketItem(itemId: string, payload?: Record<string, any>): Promise<{
    status: string
    message: string
    item: Record<string, any>
  }> {
    return this.instance.post(`/openclaw/market/items/${itemId}/install`, payload ?? {}).then(res => res.data)
  }

  getMcpStatus(): Promise<{
    server: string
    timestamp: string
    tasks: { total: number; active: number; completed: number; failed: number }
    scheduler?: Record<string, any>
  }> {
    return this.instance.get('/mcp/status').then(res => res.data)
  }

  getContextStats(days: number = 7) {
    return this.instance.get(`/logs/context/statistics?days=${days}`).then(res => res.data)
  }

  loadContext(days: number = 3) {
    return this.instance.get(`/logs/context/load?days=${days}`).then(res => res.data)
  }
}

export default new CoreApiClient(8000)
