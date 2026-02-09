import { ApiClient } from './index'

export class AgentApiClient extends ApiClient {
  getTools(): Promise<{
    success: boolean
    tools: Array<{
      name: string
      description: string
      toolkit: string
      inputSchema?: Record<string, any>
    }>
    count: number
  }> {
    return this.instance.get('/tools').then(res => res.data)
  }

  getToolkits(): Promise<{
    success: boolean
    toolkits: string[]
    count: number
  }> {
    return this.instance.get('/toolkits').then(res => res.data)
  }

  getToolkitDetail(name: string) {
    return this.instance.get(`/toolkits/${name}`).then(res => res.data)
  }

  getSessions(): Promise<{
    success: boolean
    sessions: Array<Record<string, any>>
    totalSessions: number
  }> {
    return this.instance.get('/sessions').then(res => res.data)
  }

  getSessionMemory(sessionId: string) {
    return this.instance.get(`/sessions/${sessionId}/memory`).then(res => res.data)
  }

  getSessionKeyFacts(sessionId: string): Promise<{
    success: boolean
    sessionId: string
    keyFacts: Record<string, string>
    count: number
  }> {
    return this.instance.get(`/sessions/${sessionId}/key_facts`).then(res => res.data)
  }
}

export default new AgentApiClient(8001)
