import type { Buffer } from 'node:buffer'
import type { ChildProcess } from 'node:child_process'
import { spawn, spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { app } from 'electron'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

let backendProcess: ChildProcess | null = null
let devRetryCount = 0

type AppPackageMetadata = {
  nagaDebugConsole?: boolean
}

function shouldOpenDebugConsole(): boolean {
  // 方便本地联调：手动设置环境变量可强制开启
  if (process.env.NAGA_DEBUG_CONSOLE === '1') {
    return true
  }

  if (!app.isPackaged) {
    return false
  }

  try {
    const packageJsonPath = join(app.getAppPath(), 'package.json')
    const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf-8')) as AppPackageMetadata
    return packageJson.nagaDebugConsole === true
  }
  catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.warn(`[Backend] Failed to read debug build metadata: ${message}`)
    return false
  }
}

function quoteWindowsArg(arg: string): string {
  if (arg.length === 0) {
    return '""'
  }
  if (!/[\s"]/u.test(arg)) {
    return arg
  }
  return `"${arg.replaceAll('"', '""')}"`
}

export function startBackend(): void {
  let cmd: string
  let args: string[]
  let cwd: string

  if (app.isPackaged) {
    // 打包模式：spawn PyInstaller 编译的二进制
    const backendDir = join(process.resourcesPath, 'backend')
    const ext = process.platform === 'win32' ? '.exe' : ''
    cmd = join(backendDir, `naga-backend${ext}`)
    args = []
    cwd = backendDir
  }
  else {
    // 开发模式：优先使用 venv 中的 Python 解释器，确保依赖版本一致
    cwd = join(__dirname, '..', '..')
    const venvPython = process.platform === 'win32'
      ? join(cwd, '.venv', 'Scripts', 'python.exe')
      : join(cwd, '.venv', 'bin', 'python')
    cmd = venvPython
    args = ['main.py', '--headless']
  }

  console.log(`[Backend] Starting from ${cwd}`)
  console.log(`[Backend] Command: ${cmd} ${args.join(' ')}`)

  const env = { ...process.env, PYTHONUNBUFFERED: '1' }
  const useDebugConsole = process.platform === 'win32' && shouldOpenDebugConsole()

  if (useDebugConsole) {
    const commandLine = [cmd, ...args].map(quoteWindowsArg).join(' ')
    console.log('[Backend] Debug console enabled, launching with cmd.exe /k')

    backendProcess = spawn('cmd.exe', ['/d', '/k', commandLine], {
      cwd,
      env,
      stdio: 'inherit',
      windowsHide: false,
    })

    backendProcess.on('error', (err) => {
      console.error(`[Backend] Failed to start (debug console): ${err.message}`)
    })

    backendProcess.on('exit', (code) => {
      console.log(`[Backend] Debug console exited with code ${code}`)
      backendProcess = null
    })
    return
  }

  // Dev mode: collect stderr for dependency error detection
  let stderrBuffer = ''

  backendProcess = spawn(cmd, args, {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
  })

  backendProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[Backend] ${data.toString().trimEnd()}`)
  })

  backendProcess.stderr?.on('data', (data: Buffer) => {
    const text = data.toString()
    console.error(`[Backend] ${text.trimEnd()}`)
    if (!app.isPackaged) {
      stderrBuffer += text
    }
  })

  backendProcess.on('error', (err) => {
    console.error(`[Backend] Failed to start: ${err.message}`)
  })

  backendProcess.on('exit', (code) => {
    console.log(`[Backend] Exited with code ${code}`)
    backendProcess = null

    // Dev-only auto-recovery: detect dependency errors and retry once
    if (!app.isPackaged && code === 1 && devRetryCount < 1) {
      const depErrorPattern = /ModuleNotFoundError|ImportError|No module named/u
      if (depErrorPattern.test(stderrBuffer)) {
        devRetryCount++
        console.log('[Backend] Dependency error detected, auto-installing...')

        const venvPython = process.platform === 'win32'
          ? join(cwd, '.venv', 'Scripts', 'python.exe')
          : join(cwd, '.venv', 'bin', 'python')
        const reqFile = join(cwd, 'requirements.txt')

        // Try uv first, fallback to pip
        let installOk = false
        try {
          const uvResult = spawnSync('uv', ['pip', 'install', '--python', venvPython, '-r', reqFile], {
            cwd,
            stdio: 'inherit',
            timeout: 120_000,
          })
          installOk = uvResult.status === 0
          if (!installOk && uvResult.error) {
            throw uvResult.error
          }
        }
        catch {
          console.log('[Backend] uv not available, falling back to pip...')
          const pipResult = spawnSync(venvPython, ['-m', 'pip', 'install', '-r', reqFile], {
            cwd,
            stdio: 'inherit',
            timeout: 120_000,
          })
          installOk = pipResult.status === 0
        }

        if (installOk) {
          console.log('[Backend] Dependencies installed, restarting backend...')
          startBackend()
        }
        else {
          console.error('[Backend] Dependency installation failed. Please install manually.')
        }
      }
    }
  })
}

export function stopBackend(): void {
  if (!backendProcess)
    return
  const pid = backendProcess.pid
  console.log('[Backend] Stopping...')

  if (!pid) {
    backendProcess = null
    return
  }

  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(pid), '/f', '/t'])
  } else {
    // SIGTERM 让 Python 进程 os._exit(0) 立即退出
    try {
      process.kill(pid, 'SIGTERM')
    } catch {
      // already dead
    }
    // 保险：200ms 后 SIGKILL（不 unref，确保定时器一定执行）
    setTimeout(() => {
      try {
        process.kill(pid, 'SIGKILL')
      } catch {
        // already dead
      }
    }, 200)
  }

  backendProcess = null
}
