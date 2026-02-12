import type { Live2DModel } from 'pixi-live2d-display/cubism4'
import { ref } from 'vue'

// ─── 类型 ───────────────────────────────────────────
interface Keyframe {
  t: number
  params: Record<string, number>
}

interface StateConfig {
  loop: boolean
  duration?: number
  keyframes?: Keyframe[]
  params?: Record<string, number>
  mouth?: { param: string, speed: number, min: number, max: number }
}

interface ActionConfig {
  duration: number
  repeat: number
  keyframes: Keyframe[]
}

interface ActionsData {
  states: Record<string, StateConfig>
  actions: Record<string, ActionConfig>
}

export type Live2dState = 'idle' | 'thinking' | 'talking'

// ─── 全局响应式状态 ──────────────────────────────────
export const live2dState = ref<Live2dState>('idle')
export const trackingCalibration = ref(false) // 视角校准准星开关

// ─── 内部变量 ────────────────────────────────────────
let model: Live2DModel | null = null
let actionsData: ActionsData | null = null
let stateStartTime = 0
let currentStateName: Live2dState = 'idle'
let originalUpdate: ((dt: number) => void) | null = null
let lastTickTime = 0

// 通道 1: 身体摇摆（由状态 idle/thinking/talking 控制）
// → ParamBodyAngleX, ParamAngleZ, mouth 等

// 通道 2: 头部动作（由动作队列 nod/shake 控制，正交于身体通道）
// → ParamAngleX, ParamAngleY, ParamEyeBallX, ParamEyeBallY
let actionQueue: string[] = []
let activeAction: { config: ActionConfig, startTime: number } | null = null

// 通道 3: 表情切换（未来扩展）
// → ParamEyeLOpen, ParamEyeROpen, ParamBrowLY 等

// 嘴巴状态（身体通道附属）
let mouthTarget = 0
let mouthCurrent = 0
let mouthNextChangeTime = 0

// ─── 视觉追踪（独立叠加层） ─────────────────────────
// 追踪不走状态机，直接覆盖视觉方向参数
// trackBlend 从 0（无追踪）到 1（完全追踪）丝滑过渡
let isTracking = false
let trackTargetX = 0
let trackTargetY = 0
let trackCurrentX = 0
let trackCurrentY = 0
let trackBlend = 0

// ─── 工具函数 ────────────────────────────────────────

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * Math.min(1, Math.max(0, t))
}

/** 基于 deltaTime 的平滑系数（帧率无关） */
function smoothFactor(halfLife: number, dt: number): number {
  // halfLife: 到达一半距离所需毫秒数
  if (halfLife <= 0) return 1
  return 1 - Math.exp((-0.693 / halfLife) * dt)
}

function interpolateKeyframes(keyframes: Keyframe[], progress: number): Record<string, number> {
  const result: Record<string, number> = {}
  const p = Math.max(0, Math.min(1, progress))

  let left = keyframes[0]!
  let right = keyframes[keyframes.length - 1]!
  for (let i = 0; i < keyframes.length - 1; i++) {
    if (p >= keyframes[i]!.t && p <= keyframes[i + 1]!.t) {
      left = keyframes[i]!
      right = keyframes[i + 1]!
      break
    }
  }

  const segLen = right.t - left.t
  const localT = segLen > 0 ? (p - left.t) / segLen : 0
  const smooth = localT * localT * (3 - 2 * localT)

  const allParams = new Set([...Object.keys(left.params), ...Object.keys(right.params)])
  for (const param of allParams) {
    const a = left.params[param] ?? 0
    const b = right.params[param] ?? 0
    result[param] = lerp(a, b, smooth)
  }
  return result
}

function setParam(paramId: string, value: number) {
  if (!model)
    return
  try {
    const core = (model.internalModel as any).coreModel
    if (core?.setParameterValueById) {
      core.setParameterValueById(paramId, value)
    }
  }
  catch {
    // 参数不存在则静默忽略
  }
}

// ─── 通道计算（只计算不写入） ─────────────────────────

function computeStateParams(now: number): Record<string, number> {
  if (!actionsData) return {}
  const stateCfg = actionsData.states[currentStateName]
  if (!stateCfg) return {}

  const result: Record<string, number> = {}

  if (stateCfg.keyframes && stateCfg.duration) {
    const elapsed = now - stateStartTime
    const progress = stateCfg.loop
      ? (elapsed % stateCfg.duration) / stateCfg.duration
      : Math.min(elapsed / stateCfg.duration, 1)
    Object.assign(result, interpolateKeyframes(stateCfg.keyframes, progress))
  }
  else if (stateCfg.params) {
    Object.assign(result, stateCfg.params)
  }

  return result
}

function computeMouth(now: number, dt: number): Record<string, number> {
  if (!actionsData) return {}
  const stateCfg = actionsData.states[currentStateName]
  if (!stateCfg?.mouth) return {}

  const cfg = stateCfg.mouth
  if (now >= mouthNextChangeTime) {
    mouthTarget = cfg.min + Math.random() * (cfg.max - cfg.min)
    mouthNextChangeTime = now + 80 + Math.random() * 170
  }
  // cfg.speed 越大嘴巴越慢；转换为半衰期用于帧率无关平滑
  const halfLife = cfg.speed / 3
  mouthCurrent = lerp(mouthCurrent, mouthTarget, smoothFactor(halfLife, dt))

  return { [cfg.param]: mouthCurrent }
}

function computeActionParams(now: number): Record<string, number> {
  if (!actionsData) return {}

  // 出队
  if (!activeAction && actionQueue.length > 0) {
    const actionName = actionQueue.shift()!
    const cfg = actionsData.actions[actionName]
    if (cfg) {
      activeAction = { config: cfg, startTime: now }
    }
  }

  if (!activeAction) return {}

  const { config, startTime } = activeAction
  const totalDuration = config.duration * config.repeat
  const elapsed = now - startTime

  if (elapsed >= totalDuration) {
    // 动作结束：清零动作参数
    const result: Record<string, number> = {}
    if (config.keyframes.length > 0) {
      const lastFrame = config.keyframes[config.keyframes.length - 1]!
      for (const k of Object.keys(lastFrame.params)) {
        result[k] = 0
      }
    }
    activeAction = null
    return result
  }

  const repeatElapsed = elapsed % config.duration
  const progress = repeatElapsed / config.duration
  return interpolateKeyframes(config.keyframes, progress)
}

// ─── 视觉追踪计算 ────────────────────────────────────

/** 追踪参数集：方向相关的参数由追踪接管 */
const TRACK_PARAMS: Record<string, (x: number, y: number) => number> = {
  ParamAngleX: (x, _y) => x * 30,
  ParamAngleY: (_x, y) => y * 30,
  ParamEyeBallX: (x, _y) => x,
  ParamEyeBallY: (_x, y) => y,
  ParamBodyAngleX: (x, _y) => x * 10,
}

function computeTracking(dt: number): Record<string, number> {
  // 更新混合因子：isTracking → 1, !isTracking → 0
  const blendTarget = isTracking ? 1 : 0
  const blendHalfLife = isTracking ? 60 : 120 // 开始追踪快(60ms)，松开稍慢(120ms)
  trackBlend = lerp(trackBlend, blendTarget, smoothFactor(blendHalfLife, dt))

  // 精度截断：混合因子极小时直接归零
  if (trackBlend < 0.001) {
    trackBlend = 0
    trackCurrentX = 0
    trackCurrentY = 0
    return {}
  }

  // 平滑跟随鼠标位置
  const followHalfLife = isTracking ? 40 : 80
  const sf = smoothFactor(followHalfLife, dt)
  const targetX = isTracking ? trackTargetX : 0
  const targetY = isTracking ? trackTargetY : 0
  trackCurrentX = lerp(trackCurrentX, targetX, sf)
  trackCurrentY = lerp(trackCurrentY, targetY, sf)

  const result: Record<string, number> = {}
  for (const [param, fn] of Object.entries(TRACK_PARAMS)) {
    result[param] = fn(trackCurrentX, trackCurrentY)
  }
  return result
}

// ─── 主 tick ─────────────────────────────────────────

function tick(now: number) {
  if (!actionsData) return

  const dt = lastTickTime > 0 ? Math.min(now - lastTickTime, 100) : 16
  lastTickTime = now

  // 检测状态切换
  if (currentStateName !== live2dState.value) {
    currentStateName = live2dState.value
    stateStartTime = now
    if (currentStateName !== 'talking') {
      mouthCurrent = 0
      mouthTarget = 0
    }
  }

  // ── 计算各正交通道 ──
  const stateParams = computeStateParams(now) // 通道1: 身体摇摆
  const mouthParams = computeMouth(now, dt)    // 附属: 嘴巴
  const actionParams = computeActionParams(now) // 通道2: 头部动作
  // 通道3: 表情（未来扩展）

  // 合并：后写入的覆盖先写入的（通道间参数正交所以不冲突）
  const merged: Record<string, number> = { ...stateParams, ...mouthParams, ...actionParams }

  // ── 视觉追踪混合 ──
  const trackParams = computeTracking(dt)
  if (trackBlend > 0) {
    // 对追踪参数做混合：lerp(通道值, 追踪值, blend)
    for (const [param, trackValue] of Object.entries(trackParams)) {
      const base = merged[param] ?? 0
      merged[param] = lerp(base, trackValue, trackBlend)
    }
  }

  // ── 写入所有参数 ──
  for (const [param, value] of Object.entries(merged)) {
    setParam(param, value)
  }
}

// ─── 公共 API ────────────────────────────────────────

export function triggerAction(name: string) {
  actionQueue.push(name)
}

export function startTracking() {
  isTracking = true
}

export function updateTracking(normalizedX: number, normalizedY: number) {
  trackTargetX = Math.max(-1, Math.min(1, normalizedX))
  trackTargetY = Math.max(-1, Math.min(1, normalizedY))
}

export function stopTracking() {
  isTracking = false
}

export async function initController(m: Live2DModel) {
  model = m
  lastTickTime = 0

  try {
    const resp = await fetch('/models/naga-test/naga-actions.json')
    actionsData = await resp.json()
  }
  catch (e) {
    console.warn('[Live2D Controller] 无法加载 naga-actions.json:', e)
    return
  }

  stateStartTime = performance.now()
  currentStateName = live2dState.value

  originalUpdate = model.update.bind(model)
  model.update = function (dt: number) {
    originalUpdate!(dt)
    tick(performance.now())
  }
}

export function destroyController() {
  if (model && originalUpdate) {
    model.update = originalUpdate
    originalUpdate = null
  }
  model = null
  actionsData = null
  activeAction = null
  actionQueue = []
  mouthCurrent = 0
  mouthTarget = 0
  lastTickTime = 0
  isTracking = false
  trackTargetX = 0
  trackTargetY = 0
  trackCurrentX = 0
  trackCurrentY = 0
  trackBlend = 0
}
