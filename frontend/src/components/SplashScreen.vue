<script setup lang="ts">
import { computed } from 'vue'
import NetworkCanvas from '@/components/NetworkCanvas.vue'

const props = defineProps<{
  progress: number
  phase: string
  modelReady: boolean
}>()

const emit = defineEmits<{
  dismiss: []
}>()

const canDismiss = computed(() => props.progress >= 100)
const displayProgress = computed(() => Math.min(100, Math.round(props.progress)))
</script>

<template>
  <div class="fixed inset-0 z-50 overflow-hidden select-none">
    <!-- 金色神经网络粒子动画（透明背景，Live2D 可从下层透出） -->
    <NetworkCanvas />

    <!-- clip-path evenodd 开洞遮罩：中间矩形区域透明，四周深色 -->
    <div class="frame-mask" />

    <!-- 矩形框金色边框 -->
    <div class="frame-border" />

    <!-- 底部进度区域 -->
    <div class="absolute bottom-12 left-1/2 -translate-x-1/2 w-60% flex flex-col items-center gap-2">
      <!-- 阶段文字 + 百分比 -->
      <div class="flex justify-between w-full px-1 text-xs tracking-widest"
           style="color: rgba(212, 175, 55, 0.7); font-family: 'Segoe UI', sans-serif;">
        <span>{{ phase }}</span>
        <span>{{ displayProgress }}%</span>
      </div>
      <!-- 进度条轨道 -->
      <div class="w-full h-0.5 rounded-full" style="background: rgba(212, 175, 55, 0.15);">
        <div
          class="h-full rounded-full transition-all duration-300 ease-out"
          style="background: linear-gradient(90deg, rgba(212, 175, 55, 0.4), rgba(212, 175, 55, 0.9));"
          :style="{ width: `${displayProgress}%` }"
        />
      </div>
    </div>

    <!-- 点击进入提示 -->
    <Transition name="fade">
      <div
        v-if="canDismiss"
        class="absolute inset-0 flex items-end justify-center pb-28 cursor-pointer"
        @click="emit('dismiss')"
      >
        <span class="click-hint text-sm tracking-[0.3em]" style="color: rgba(212, 175, 55, 0.8);">
          点 击 进 入
        </span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.frame-mask {
  position: absolute;
  inset: 0;
  /* 居中矩形开洞 - 宽度约36vw, 高度约52vh, 稍偏上 */
  --frame-w: 36vw;
  --frame-h: 52vh;
  --frame-x: calc(50% - var(--frame-w) / 2);
  --frame-y: calc(38% - var(--frame-h) / 2);
  /* evenodd 填充规则：内外路径交叉区域镂空 */
  clip-path: polygon(
    evenodd,
    0% 0%, 100% 0%, 100% 100%, 0% 100%,
    var(--frame-x) var(--frame-y),
    var(--frame-x) calc(var(--frame-y) + var(--frame-h)),
    calc(var(--frame-x) + var(--frame-w)) calc(var(--frame-y) + var(--frame-h)),
    calc(var(--frame-x) + var(--frame-w)) var(--frame-y)
  );
  background: rgba(0, 0, 0, 0.85);
  pointer-events: none;
}

.frame-border {
  position: absolute;
  width: 36vw;
  height: 52vh;
  left: 50%;
  top: 38%;
  transform: translate(-50%, -50%);
  border: 1px solid rgba(212, 175, 55, 0.4);
  box-shadow: 0 0 15px rgba(212, 175, 55, 0.15), inset 0 0 15px rgba(212, 175, 55, 0.05);
  pointer-events: none;
}

/* 点击进入脉冲动画 */
.click-hint {
  animation: pulse-gold 2s ease-in-out infinite;
}

@keyframes pulse-gold {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; text-shadow: 0 0 12px rgba(212, 175, 55, 0.5); }
}

/* 内部元素淡入 */
.fade-enter-active {
  transition: opacity 0.6s ease;
}
.fade-enter-from {
  opacity: 0;
}
</style>
