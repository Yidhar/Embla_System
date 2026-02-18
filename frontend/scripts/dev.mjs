import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const projectRoot = join(__dirname, '..')
const viteArgs = process.argv.slice(2)

function quoteWindowsArg(arg) {
  if (arg.length === 0)
    return '""'
  if (!/[\s"&|^<>]/u.test(arg))
    return arg
  return `"${arg.replaceAll('"', '""')}"`
}

const child = process.platform === 'win32'
  ? spawn('cmd.exe', [
      '/d',
      '/s',
      '/c',
      `chcp 65001>nul && npx vite ${viteArgs.map(quoteWindowsArg).join(' ')}`.trim(),
    ], {
      cwd: projectRoot,
      stdio: 'inherit',
      env: process.env,
      windowsHide: false,
    })
  : spawn('npx', ['vite', ...viteArgs], {
      cwd: projectRoot,
      stdio: 'inherit',
      env: process.env,
    })

child.on('error', (error) => {
  console.error(`[dev] failed to start vite: ${error.message}`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
