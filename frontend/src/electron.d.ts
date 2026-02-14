export type FloatingState = 'classic' | 'ball' | 'compact' | 'full'

export interface CaptureSource {
  id: string
  name: string
  thumbnail: string
  appIcon: string | null
}

export interface CaptureAPI {
  getSources: () => Promise<CaptureSource[]>
  captureWindow: (sourceId: string) => Promise<string | null>
}

export interface BackendAPI {
  onProgress: (callback: (payload: { percent: number, phase: string }) => void) => () => void
  onError: (callback: (payload: { code: number, logs: string }) => void) => () => void
}

export interface FloatingAPI {
  enter: () => Promise<void>
  exit: () => Promise<void>
  expand: (toFull?: boolean) => Promise<void>
  expandToFull: () => Promise<void>
  collapse: () => Promise<void>
  collapseToCompact: () => Promise<void>
  getState: () => Promise<FloatingState>
  pin: (value: boolean) => void
  fitHeight: (height: number) => void
  setPosition: (x: number, y: number) => void
  onStateChange: (callback: (state: FloatingState) => void) => () => void
  onWindowBlur: (callback: () => void) => () => void
}

export interface ElectronAPI {
  minimize: () => void
  maximize: () => void
  close: () => void
  isMaximized: () => Promise<boolean>
  onMaximized: (callback: (maximized: boolean) => void) => () => void
  downloadUpdate: () => void
  installUpdate: () => void
  onUpdateAvailable: (callback: (info: { version: string, releaseNotes: string }) => void) => () => void
  onUpdateDownloaded: (callback: () => void) => () => void
  floating: FloatingAPI
  capture: CaptureAPI
  backend: BackendAPI
  platform: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
