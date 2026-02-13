import { contextBridge, ipcRenderer } from 'electron'

const electronAPI = {
  // Window controls
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),

  // Window state events
  onMaximized: (callback: (maximized: boolean) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized)
    ipcRenderer.on('window:maximized', handler)
    return () => ipcRenderer.removeListener('window:maximized', handler)
  },

  // Updater
  downloadUpdate: () => ipcRenderer.send('updater:download'),
  installUpdate: () => ipcRenderer.send('updater:install'),

  onUpdateAvailable: (callback: (info: { version: string, releaseNotes: string }) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, info: { version: string, releaseNotes: string }) => callback(info)
    ipcRenderer.on('updater:update-available', handler)
    return () => ipcRenderer.removeListener('updater:update-available', handler)
  },
  onUpdateDownloaded: (callback: () => void) => {
    const handler = () => callback()
    ipcRenderer.on('updater:update-downloaded', handler)
    return () => ipcRenderer.removeListener('updater:update-downloaded', handler)
  },

  // 悬浮球模式控制
  floating: {
    enter: () => ipcRenderer.invoke('floating:enter'),
    exit: () => ipcRenderer.invoke('floating:exit'),
    expand: (toFull?: boolean) => ipcRenderer.invoke('floating:expand', toFull),
    expandToFull: () => ipcRenderer.invoke('floating:expandToFull'),
    collapse: () => ipcRenderer.invoke('floating:collapse'),
    collapseToCompact: () => ipcRenderer.invoke('floating:collapseToCompact'),
    getState: () => ipcRenderer.invoke('floating:getState') as Promise<'classic' | 'ball' | 'compact' | 'full'>,
    pin: (value: boolean) => ipcRenderer.send('floating:pin', value),
    fitHeight: (height: number) => ipcRenderer.send('floating:fitHeight', height),
    setPosition: (x: number, y: number) => ipcRenderer.send('floating:setPosition', x, y),
    onStateChange: (callback: (state: 'classic' | 'ball' | 'compact' | 'full') => void) => {
      const handler = (_event: Electron.IpcRendererEvent, state: 'classic' | 'ball' | 'compact' | 'full') => callback(state)
      ipcRenderer.on('floating:stateChanged', handler)
      return () => ipcRenderer.removeListener('floating:stateChanged', handler)
    },
    onWindowBlur: (callback: () => void) => {
      const handler = () => callback()
      ipcRenderer.on('floating:windowBlur', handler)
      return () => ipcRenderer.removeListener('floating:windowBlur', handler)
    },
  },

  // 窗口截屏功能
  capture: {
    getSources: () => ipcRenderer.invoke('capture:getSources') as Promise<Array<{
      id: string
      name: string
      thumbnail: string
      appIcon: string | null
    }>>,
    captureWindow: (sourceId: string) => ipcRenderer.invoke('capture:captureWindow', sourceId) as Promise<string | null>,
  },

  // Platform info
  platform: process.platform,
}

contextBridge.exposeInMainWorld('electronAPI', electronAPI)
