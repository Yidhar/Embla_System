import { ref, watch } from 'vue'
import { backendConnected } from '@/utils/config'
import { preloadAllViews } from '@/utils/viewPreloader'
import API from '@/api/core'

export function useStartupProgress() {
  const progress = ref(0)
  const phase = ref<string>('初始化...')
  const isReady = ref(false)

  let targetProgress = 0
  let rafId = 0
  let modelReady = false
  let unsubProgress: (() => void) | undefined

  // requestAnimationFrame 驱动的丝滑插值
  function animateProgress() {
    const diff = targetProgress - progress.value
    if (Math.abs(diff) > 0.1) {
      progress.value += diff * 0.08
    }
    else {
      progress.value = targetProgress
    }

    if (progress.value >= 100) {
      progress.value = 100
      isReady.value = true
    }

    if (!isReady.value || progress.value < 100) {
      rafId = requestAnimationFrame(animateProgress)
    }
  }

  function setTarget(value: number, newPhase: string) {
    if (value > targetProgress) {
      targetProgress = value
      phase.value = newPhase
    }
  }

  // 外部通知：Live2D 模型加载完成
  function notifyModelReady() {
    modelReady = true
    setTarget(25, '连接后端...')
  }

  async function runPostConnect() {
    // 取消后端进度监听
    unsubProgress?.()
    unsubProgress = undefined

    // 阶段 25→50：后端已连接
    setTarget(50, '预加载视图...')

    // 阶段 50→70：预加载视图
    await preloadAllViews((loaded, total) => {
      const viewProgress = 50 + (loaded / total) * 20
      setTarget(viewProgress, '预加载视图...')
    })

    // 阶段 70→90：获取会话
    setTarget(70, '获取会话...')
    try {
      await API.getSessions()
    }
    catch {
      // 会话获取失败不阻塞启动
    }
    setTarget(90, '准备就绪')

    // 阶段 90→100：完成
    setTimeout(() => setTarget(100, '准备就绪'), 300)
  }

  async function startProgress() {
    // 阶段 0→10：初始化
    setTarget(10, modelReady ? '连接后端...' : '加载模型...')
    rafId = requestAnimationFrame(animateProgress)

    // 监听后端进度信号（Electron 环境）
    const api = window.electronAPI
    if (api?.backend) {
      unsubProgress = api.backend.onProgress((payload) => {
        // 后端 percent 0~50 映射到前端 10~50 区间
        const mapped = 10 + (payload.percent / 50) * 40
        setTarget(Math.min(mapped, 50), payload.phase)
      })
    }

    // 如果后端已连接（HMR/重复挂载），直接推进
    if (backendConnected.value) {
      runPostConnect()
      return
    }

    // 监听后端连接
    const stopWatch = watch(backendConnected, (connected) => {
      if (!connected) return
      stopWatch()
      runPostConnect()
    })
  }

  function cleanup() {
    if (rafId) cancelAnimationFrame(rafId)
    unsubProgress?.()
  }

  return {
    progress,
    phase,
    isReady,
    startProgress,
    notifyModelReady,
    cleanup,
  }
}
