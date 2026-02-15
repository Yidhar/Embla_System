import process from 'node:process'
import { app, BrowserWindow, desktopCapturer, ipcMain, Menu, nativeTheme, shell, systemPreferences } from 'electron'
import { startBackend, stopBackend } from './modules/backend'
import { registerHotkeys, unregisterHotkeys } from './modules/hotkeys'
import { createMenu } from './modules/menu'
import { createTray, destroyTray } from './modules/tray'
import { downloadUpdate, installUpdate, setupAutoUpdater } from './modules/updater'
import {
  collapseFloatingWindow,
  collapseFullToCompact,
  createWindow,
  enterFloatingMode,
  exitFloatingMode,
  expandCompactToFull,
  expandFloatingWindow,
  getFloatingState,
  getMainWindow,
  setFloatingHeight,
  setWindowPosition,
} from './modules/window'

let isQuitting = false

// Prevent multiple instances
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
}

app.on('second-instance', () => {
  const win = getMainWindow()
  if (win) {
    if (win.isMinimized())
      win.restore()
    win.show()
    win.focus()
  }
})

app.whenReady().then(() => {
  // 强制暗色主题（确保原生菜单等 UI 为深色）
  nativeTheme.themeSource = 'dark'

  // Start backend services
  startBackend()

  // Create menu
  createMenu()

  // Create main window
  const win = createWindow()

  // Create system tray
  createTray()

  // Register global hotkeys
  registerHotkeys()

  // Setup auto-updater
  setupAutoUpdater(win)

  // --- IPC Handlers ---

  // Window controls
  ipcMain.on('window:minimize', () => getMainWindow()?.minimize())
  ipcMain.on('window:maximize', () => {
    const w = getMainWindow()
    if (w) {
      w.isMaximized() ? w.unmaximize() : w.maximize()
    }
  })
  ipcMain.on('window:close', () => {
    const state = getFloatingState()
    if (state === 'compact' || state === 'full') {
      // 悬浮球展开态：收起为球态
      collapseFloatingWindow()
    }
    else if (state === 'classic') {
      // 经典模式：关闭窗口 → 自动进入悬浮球
      enterFloatingMode()
    }
    else {
      // 已经是球态，隐藏到托盘
      getMainWindow()?.hide()
    }
  })

  ipcMain.handle('window:isMaximized', () => getMainWindow()?.isMaximized() ?? false)

  // 悬浮球模式控制
  ipcMain.handle('floating:enter', () => {
    enterFloatingMode()
  })
  ipcMain.handle('floating:exit', () => {
    exitFloatingMode()
  })
  ipcMain.handle('floating:expand', (_event, toFull?: boolean) => {
    expandFloatingWindow(toFull ?? false)
  })
  ipcMain.handle('floating:expandToFull', () => {
    expandCompactToFull()
  })
  ipcMain.handle('floating:collapse', () => {
    collapseFloatingWindow()
  })
  ipcMain.handle('floating:collapseToCompact', () => {
    collapseFullToCompact()
  })
  ipcMain.handle('floating:getState', () => getFloatingState())
  ipcMain.on('floating:pin', (_event, pinned: boolean) => {
    const w = getMainWindow()
    if (w) {
      // 固定时显示任务栏图标，取消固定时隐藏（悬浮球模式下 alwaysOnTop 始终为 true）
      w.setSkipTaskbar(!pinned)
    }
  })
  ipcMain.on('floating:setPosition', (_event, x: number, y: number) => {
    setWindowPosition(x, y)
  })
  ipcMain.on('floating:fitHeight', (_event, height: number) => {
    setFloatingHeight(height)
  })

  // Update controls
  ipcMain.on('updater:download', () => downloadUpdate())
  ipcMain.on('updater:install', () => installUpdate())

  // App quit
  ipcMain.on('app:quit', () => {
    isQuitting = true
    app.quit()
  })

  // 悬浮球右键菜单
  ipcMain.on('context-menu:show', () => {
    const menu = Menu.buildFromTemplate([
      {
        label: '打开主界面',
        click: () => exitFloatingMode(),
      },
      {
        label: '隐藏到托盘',
        click: () => getMainWindow()?.hide(),
      },
      { type: 'separator' },
      {
        label: '退出应用',
        click: () => {
          isQuitting = true
          app.quit()
        },
      },
    ])
    menu.popup()
  })

  // 窗口截屏功能
  ipcMain.handle('capture:getSources', async () => {
    // macOS 需要屏幕录制权限
    if (process.platform === 'darwin') {
      const status = systemPreferences.getMediaAccessStatus('screen')
      if (status !== 'granted') {
        return { permission: status }
      }
    }

    try {
      const sources = await desktopCapturer.getSources({
        types: ['window', 'screen'],
        thumbnailSize: { width: 320, height: 180 },
        fetchWindowIcons: true,
      })
      return sources.map(s => ({
        id: s.id,
        name: s.name,
        thumbnail: s.thumbnail.toDataURL(),
        appIcon: s.appIcon?.toDataURL() || null,
      }))
    }
    catch {
      // desktopCapturer 可能因权限问题抛出异常
      return { permission: 'denied' }
    }
  })

  ipcMain.handle('capture:captureWindow', async (_event, sourceId: string) => {
    const sources = await desktopCapturer.getSources({
      types: ['window', 'screen'],
      thumbnailSize: { width: 1920, height: 1080 },
    })
    const target = sources.find(s => s.id === sourceId)
    if (!target)
      return null
    return target.thumbnail.toDataURL()
  })

  // 打开 macOS 屏幕录制权限设置
  ipcMain.handle('capture:openScreenSettings', async () => {
    if (process.platform === 'darwin') {
      await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture')
    }
  })

  // 开机自启动
  ipcMain.handle('autoLaunch:get', () => {
    return app.getLoginItemSettings().openAtLogin
  })
  ipcMain.handle('autoLaunch:set', (_event, enabled: boolean) => {
    app.setLoginItemSettings({ openAtLogin: enabled })
  })

  // Minimize to tray on close instead of quitting
  win.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      win.hide()
    }
  })

  win.on('maximize', () => win.webContents.send('window:maximized', true))
  win.on('unmaximize', () => win.webContents.send('window:maximized', false))

  // 悬浮球展开态失焦时自动收起（由渲染进程控制是否启用）
  win.on('blur', () => {
    win.webContents.send('floating:windowBlur')
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
    else {
      getMainWindow()?.show()
    }
  })
})

app.on('before-quit', () => {
  isQuitting = true
})

app.on('will-quit', () => {
  unregisterHotkeys()
  destroyTray()
  stopBackend()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
