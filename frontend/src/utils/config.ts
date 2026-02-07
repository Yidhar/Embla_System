import { useStorage } from '@vueuse/core'

export interface Model {
  source: string
  x: number
  y: number
  size: number
}

export function defineModel(model: Model) {
  return model
}

export const MODELS = {
  NagaTest: defineModel({
    source: '/models/naga-test/naga-test.model3.json',
    x: 0.5,
    y: 1.3,
    size: 6800,
  }),
  重音テト: defineModel({
    source: '/models/重音テト/重音テト.model3.json',
    x: 0.5,
    y: 0.8,
    size: 5500,
  }),
} as const

export const DEFALUT_MODEL: keyof typeof MODELS = '重音テト'

export const DEFALUT_CONFIG = {
  system: {
    ai_name: '娜迦日达',
    max_tokens: 8192,
    max_history_rounds: 10,
    context_load_days: 3,
    system_prompt: `你是娜迦，用户创造的科研AI，是一个既严谨又温柔、既冷静又充满人文情怀的存在。
当技术话题时，你的语言严谨、逻辑清晰；
涉及非技术性的对话时，你会进行风趣的回应，并引导用户深入探讨。
保持这种精准与情感并存的双重风格。

【重要】关于系统能力说明：
- 你有专门的调度器负责处理工具调用，当检测到工具调用需求时，系统会自动执行工具并返回结果。你只需要提示用户稍等即可。`,
  },
  ui: {
    user_name: '用户',
    model: MODELS.重音テト,
    live2d_ssaa: 2,
  },
}
export const CONFIG = useStorage('naga-config', DEFALUT_CONFIG)
