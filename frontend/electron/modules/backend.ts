import { spawn } from 'child_process'
import type { ChildProcess } from 'child_process'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'
import { app } from 'electron'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

let backendProcess: ChildProcess | null = null

export function startBackend(): void {
  // Project root is parent of frontend/
  const projectRoot = app.isPackaged
    ? join(process.resourcesPath)
    : join(__dirname, '..', '..')

  // Try 'uv run main.py' first, fallback to 'python main.py'
  const cmd = process.platform === 'win32' ? 'python' : 'python3'

  console.log(`[Backend] Starting from ${projectRoot}`)

  backendProcess = spawn(cmd, ['main.py', '--headless'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  })

  backendProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[Backend] ${data.toString().trimEnd()}`)
  })

  backendProcess.stderr?.on('data', (data: Buffer) => {
    console.error(`[Backend] ${data.toString().trimEnd()}`)
  })

  backendProcess.on('error', (err) => {
    console.error(`[Backend] Failed to start: ${err.message}`)
  })

  backendProcess.on('exit', (code) => {
    console.log(`[Backend] Exited with code ${code}`)
    backendProcess = null
  })
}

export function stopBackend(): void {
  if (!backendProcess) return
  console.log('[Backend] Stopping...')

  if (process.platform === 'win32') {
    // On Windows, use taskkill to kill the process tree
    spawn('taskkill', ['/pid', String(backendProcess.pid), '/f', '/t'])
  } else {
    backendProcess.kill('SIGTERM')
    // Force kill after 5s if still alive
    const pid = backendProcess.pid
    setTimeout(() => {
      try {
        if (pid) process.kill(pid, 0) // check if alive
        process.kill(pid!, 'SIGKILL')
      } catch {
        // already dead
      }
    }, 5000)
  }

  backendProcess = null
}
