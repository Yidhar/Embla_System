import { ref, watch } from 'vue'
import { backendConnected } from '@/utils/config'
import { preloadAllViews } from '@/utils/viewPreloader'
import API from '@/api/core'

export function useStartupProgress() {
  const progress = ref(0)
  const phase = ref<string>('初始化...')
  const isReady = ref(false)
  const stallHint = ref(false)

  let targetProgress = 0
  let rafId = 0
  let modelReady = false
  let unsubProgress: (() => void) | undefined
  let lastProgressValue = 0
  let lastProgressChangeTime = Date.now()
  let healthPollTimer: ReturnType<typeof setInterval> | undefined

  // 停滞检测：进度 3 秒无变化 → 显示提示
  function checkStall() {
    const now = Date.now()
    if (progress.value !== lastProgressValue) {
      lastProgressValue = progress.value
      lastProgressChangeTime = now
      stallHint.value = false
    }
    else if (!stallHint.value && now - lastProgressChangeTime >= 3000 && progress.value < 100) {
      stallHint.value = true
      console.warn(`[Startup] 进度停滞在 ${progress.value.toFixed(1)}%，已超过 3 秒`)
    }
  }

  // requestAnimationFrame 驱动的丝滑插值
  function animateProgress() {
    const diff = targetProgress - progress.value
    if (diff > 0.5) {
      // 比例追赶 + 最低速度，避免接近目标时卡顿
      progress.value = Math.min(progress.value + Math.max(diff * 0.12, 0.5), targetProgress)
    }
    else if (diff > 0) {
      progress.value = targetProgress
    }

    if (progress.value >= 100) {
      progress.value = 100
      isReady.value = true
    }

    checkStall()

    if (!isReady.value || progress.value < 100) {
      rafId = requestAnimationFrame(animateProgress)
    }
  }

  function setTarget(value: number, newPhase: string) {
    if (value > targetProgress) {
      console.log(`[Startup] 进度 ${targetProgress.toFixed(0)}% → ${value.toFixed(0)}%  阶段: ${newPhase}`)
      targetProgress = value
      phase.value = newPhase
    }
  }

  // 外部通知：Live2D 模型加载完成
  function notifyModelReady() {
    modelReady = true
    console.log('[Startup] Live2D 模型就绪')
    setTarget(25, '连接后端...')
  }

  // 轮询后端健康检查，确保不会卡在 50%
  function startHealthPolling() {
    if (healthPollTimer) return
    console.log('[Startup] 开始轮询后端健康状态...')
    healthPollTimer = setInterval(async () => {
      try {
        await API.health()
        if (!backendConnected.value) {
          console.log('[Startup] 健康轮询成功，后端已就绪，但 backendConnected 尚未置位')
        }
        // 如果后端健康但还卡在 50% 以下，强制推进
        if (targetProgress <= 50 && !backendConnected.value) {
          console.log('[Startup] 健康轮询检测到后端就绪，手动触发 postConnect')
          backendConnected.value = true
        }
      }
      catch {
        // 后端尚未就绪，继续轮询
      }
    }, 1000)
  }

  function stopHealthPolling() {
    if (healthPollTimer) {
      clearInterval(healthPollTimer)
      healthPollTimer = undefined
    }
  }

  async function runPostConnect() {
    // 取消后端进度监听和健康轮询
    unsubProgress?.()
    unsubProgress = undefined
    stopHealthPolling()

    // 阶段 25→50：后端已连接
    console.log('[Startup] 后端已连接，开始视图预加载')
    setTarget(50, '预加载视图...')

    // 阶段 50→70：预加载视图
    await preloadAllViews((loaded, total) => {
      const viewProgress = 50 + (loaded / total) * 20
      console.log(`[Startup] 预加载视图 ${loaded}/${total}`)
      setTarget(viewProgress, '预加载视图...')
    })

    // 阶段 70→90：获取会话
    setTarget(70, '获取会话...')
    try {
      await API.getSessions()
      console.log('[Startup] 会话获取完成')
    }
    catch {
      console.warn('[Startup] 会话获取失败，不阻塞启动')
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

    // 到达 25% 后开始轮询后端健康状态（防止信号丢失卡在 50%）
    const stopPollWatch = watch(() => progress.value >= 25, (ready) => {
      if (!ready) return
      stopPollWatch()
      startHealthPolling()
    })

    // 监听后端连接
    const stopWatch = watch(backendConnected, (connected) => {
      if (!connected) return
      stopWatch()
      stopPollWatch()
      runPostConnect()
    })
  }

  function cleanup() {
    if (rafId) cancelAnimationFrame(rafId)
    unsubProgress?.()
    stopHealthPolling()
  }

  return {
    progress,
    phase,
    isReady,
    stallHint,
    startProgress,
    notifyModelReady,
    cleanup,
  }
}
