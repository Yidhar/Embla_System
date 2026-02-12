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
export type EmotionState = 'normal' | 'happy' | 'enjoy' | 'sad' | 'surprise'

// ─── 全局响应式状态 ──────────────────────────────────
export const live2dState = ref<Live2dState>('idle')
export const trackingCalibration = ref(false)

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

// 通道 3a: Emotion 表情（由 setEmotion 驱动，从 naga-actions.json 读关键帧）
let currentExpressionState: EmotionState | null = null
let expressionStartTime = 0

// 通道 3b: 手动参数覆盖（由 setExpression 驱动，用于开屏闭眼等）
let expressionTarget: Record<string, number> = {}
let expressionCurrent: Record<string, number> = {}
let expressionActive = false

// 嘴巴状态（身体通道附属）
let mouthTarget = 0
let mouthCurrent = 0
let mouthNextChangeTime = 0

// ─── 通道3: 表情计算 ─────────────────────────────────

/** 表情参数的默认值（清除表情时回归的目标） */
const EXPRESSION_DEFAULTS: Record<string, number> = {
  ParamEyeLOpen: 1,
  ParamEyeROpen: 1,
  ParamEyeLSmile: 0,
  ParamEyeRSmile: 0,
  ParamBrowLY: 0,
  ParamBrowRY: 0,
  ParamMouthForm: 0,
}

function computeExpression(dt: number): Record<string, number> {
  if (!expressionActive && Object.keys(expressionCurrent).length === 0) return {}

  const allParams = new Set([...Object.keys(expressionTarget), ...Object.keys(expressionCurrent)])
  const halfLife = 100 // 100ms 平滑过渡
  const sf = smoothFactor(halfLife, dt)
  const result: Record<string, number> = {}
  const toDelete: string[] = []

  for (const param of allParams) {
    const target = expressionActive
      ? (expressionTarget[param] ?? EXPRESSION_DEFAULTS[param] ?? 0)
      : (EXPRESSION_DEFAULTS[param] ?? 0)
    const current = expressionCurrent[param] ?? EXPRESSION_DEFAULTS[param] ?? 0
    const newVal = lerp(current, target, sf)
    expressionCurrent[param] = newVal
    result[param] = newVal

    // 参数已回归默认且不再激活，清理
    if (!expressionActive) {
      const defaultVal = EXPRESSION_DEFAULTS[param] ?? 0
      if (Math.abs(newVal - defaultVal) < 0.001) {
        toDelete.push(param)
      }
    }
  }

  for (const k of toDelete) {
    delete expressionCurrent[k]
  }

  return result
}

// ─── 视觉追踪（独立叠加层） ─────────────────────────
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

function smoothFactor(halfLife: number, dt: number): number {
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
  const halfLife = cfg.speed / 3
  mouthCurrent = lerp(mouthCurrent, mouthTarget, smoothFactor(halfLife, dt))

  return { [cfg.param]: mouthCurrent }
}

function computeActionParams(now: number): Record<string, number> {
  if (!actionsData) return {}

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

function computeExpressionParams(now: number): Record<string, { value: number, blend: 'add' | 'multiply' | 'overwrite' }> {
  if (!currentExpressionState || !actionsData)
    return {}

  const stateCfg = actionsData.states[currentExpressionState]
  if (!stateCfg || !stateCfg.keyframes || !stateCfg.duration)
    return {}

  const elapsed = now - expressionStartTime
  const progress = Math.min(elapsed / stateCfg.duration, 1)

  const result: Record<string, { value: number, blend: 'add' | 'multiply' | 'overwrite' }> = {}
  const params = interpolateKeyframes(stateCfg.keyframes, progress)

  for (const [param, value] of Object.entries(params)) {
    result[param] = { value, blend: 'overwrite' }
  }

  return result
}

// ─── 视觉追踪计算 ────────────────────────────────────

const TRACK_PARAMS: Record<string, (x: number, y: number) => number> = {
  ParamAngleX: (x, _y) => x * 30,
  ParamAngleY: (_x, y) => y * 30,
  ParamEyeBallX: (x, _y) => x,
  ParamEyeBallY: (_x, y) => y,
  ParamBodyAngleX: (x, _y) => x * 10,
}

function computeTracking(dt: number): Record<string, number> {
  const blendTarget = isTracking ? 1 : 0
  const blendHalfLife = isTracking ? 60 : 120
  trackBlend = lerp(trackBlend, blendTarget, smoothFactor(blendHalfLife, dt))

  if (trackBlend < 0.001) {
    trackBlend = 0
    trackCurrentX = 0
    trackCurrentY = 0
    return {}
  }

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

  if (currentStateName !== live2dState.value) {
    currentStateName = live2dState.value
    stateStartTime = now
    if (currentStateName !== 'talking') {
      mouthCurrent = 0
      mouthTarget = 0
    }
    if (currentStateName === 'idle') {
      currentExpressionState = null
    }
  }

  // ── 计算各正交通道 ──
  const stateParams = computeStateParams(now) // 通道1: 身体摇摆
  const mouthParams = computeMouth(now, dt)    // 附属: 嘴巴
  const actionParams = computeActionParams(now) // 通道2: 头部动作
  const expressionParams = computeExpressionParams(now) // 通道3a: Emotion表情
  const exprParams = computeExpression(dt)      // 通道3b: 手动参数覆盖

  // 合并：后写入的覆盖先写入的（通道间参数正交所以不冲突）
  const merged: Record<string, number> = { ...stateParams, ...mouthParams, ...actionParams, ...exprParams }

  for (const [param, { value, blend }] of Object.entries(expressionParams)) {
    switch (blend) {
      case 'add':
        merged[param] = (merged[param] || 0) + value
        break
      case 'multiply':
        merged[param] = (merged[param] || 1) * value
        break
      case 'overwrite':
        merged[param] = value
        break
    }
  }

  const trackParams = computeTracking(dt)
  if (trackBlend > 0) {
    for (const [param, trackValue] of Object.entries(trackParams)) {
      const base = merged[param] ?? 0
      merged[param] = lerp(base, trackValue, trackBlend)
    }
  }

  for (const [param, value] of Object.entries(merged)) {
    setParam(param, value)
  }
}

// ─── 公共 API ────────────────────────────────────────

export async function setEmotion(emotion: 'normal' | 'positive' | 'negative' | 'surprise') {
  const positiveExpressions: readonly ['happy', 'enjoy'] = ['happy', 'enjoy']
  let targetExpression: EmotionState

  switch (emotion) {
    case 'normal':
      targetExpression = 'normal'
      break
    case 'positive':
      targetExpression = positiveExpressions[Math.floor(Math.random() * positiveExpressions.length)]!
      break
    case 'negative':
      targetExpression = 'sad'
      break
    case 'surprise':
      targetExpression = 'surprise'
      break
    default:
      targetExpression = 'normal'
  }

  currentExpressionState = targetExpression
  expressionStartTime = performance.now()
}

export function triggerAction(name: string) {
  actionQueue.push(name)
}

/** 设置表情通道参数覆盖（如闭眼：{ ParamEyeLOpen: 0, ParamEyeROpen: 0 }） */
export function setExpression(params: Record<string, number>) {
  expressionTarget = { ...params }
  expressionActive = true
}

/** 清除表情覆盖，参数平滑回归默认值 */
export function clearExpression() {
  expressionActive = false
  expressionTarget = {}
}

/** 触发模型内置 SDK 表情（expression1-9: happy, sad, enjoy, surprise 等） */
export function triggerModelExpression(name: string) {
  if (!model) return
  try {
    ;(model as any).expression(name)
  }
  catch {
    // 表情不存在则静默忽略
  }
}

export function startTracking() {
  isTracking = true
}

export function stopTracking() {
  isTracking = false
}

export function updateTracking(x: number, y: number) {
  trackTargetX = x
  trackTargetY = y
}

export async function initController(modelInstance: Live2DModel) {
  model = modelInstance

  const response = await fetch('/models/naga-test/naga-actions.json')
  actionsData = await response.json() as ActionsData

  originalUpdate = model.update.bind(model)
  model.update = function (dt: number) {
    const now = performance.now()
    originalUpdate!(dt)
    tick(now)
  }
}

export function destroyController() {
  if (model && originalUpdate) {
    model.update = originalUpdate
  }
  model = null
  actionsData = null
  originalUpdate = null
  currentExpressionState = null
  actionQueue = []
  expressionTarget = {}
  expressionCurrent = {}
  expressionActive = false
  activeAction = null
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
