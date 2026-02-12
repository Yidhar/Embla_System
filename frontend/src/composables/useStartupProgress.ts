import { ref, watch } from 'vue'
import { backendConnected } from '@/utils/config'
import { preloadAllViews } from '@/utils/viewPreloader'
import API from '@/api/core'

type Phase =
  | '初始化...'
  | '加载模型...'
  | '连接后端...'
  | '预加载视图...'
  | '获取会话...'
  | '准备就绪'

export function useStartupProgress() {
  const progress = ref(0)
  const phase = ref<Phase>('初始化...')
  const isReady = ref(false)

  let targetProgress = 0
  let rafId = 0
  let modelReady = false

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

  function setTarget(value: number, newPhase: Phase) {
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
