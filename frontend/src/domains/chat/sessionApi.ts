import API from '@/api/core'

export interface SessionSummary {
  sessionId: string
  createdAt: string
  lastActiveAt: string
  conversationRounds: number
  temporary: boolean
}

export async function getSessions(): Promise<SessionSummary[]> {
  const response = await API.getSessions()
  return response.sessions ?? []
}

export function deleteSession(sessionId: string) {
  return API.deleteSession(sessionId)
}

export function parseDocument(file: File) {
  return API.parseDocument(file)
}

export function uploadDocument(file: File) {
  return API.uploadDocument(file)
}
