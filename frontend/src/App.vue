<script setup lang="ts">
import { useWindowSize } from '@vueuse/core'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Live2dModel from '@/components/Live2dModel.vue'
import SplashScreen from '@/components/SplashScreen.vue'
import TitleBar from '@/components/TitleBar.vue'
import { useParallax } from '@/composables/useParallax'
import { useStartupProgress } from '@/composables/useStartupProgress'
import { CONFIG } from '@/utils/config'
import { initParallax, destroyParallax } from '@/utils/parallax'

const isElectron = !!window.electronAPI

const { width, height } = useWindowSize()
const scale = computed(() => height.value / (10000 - CONFIG.value.web_live2d.model.size))

// ─── 伪3D 视差 ────────────────────────────
const { tx: lightTx, ty: lightTy } = useParallax({ translateX: 25, translateY: 18, invert: true })

// ─── 启动界面状态 ───────────────────────────
const { progress, phase, isReady, startProgress, notifyModelReady, cleanup } = useStartupProgress()
const splashVisible = ref(true)
const showMainContent = ref(false)
const modelReady = ref(false)

// Live2D 居中/过渡控制
const live2dTransform = ref('')
const live2dTransition = ref(false)

// 记录首次 model-ready 是否已处理（避免 watch 重复触发时反复设置 transform）
let initialPositionSet = false

function onModelReady(pos: { faceX: number, faceY: number }) {
  if (!modelReady.value) {
    modelReady.value = true
    notifyModelReady()
  }

  // splash 阶段：将 Live2D 面部居中到矩形框中央
  if (splashVisible.value && !initialPositionSet) {
    initialPositionSet = true
    const cx = window.innerWidth / 2
    const cy = window.innerHeight * 0.42
    live2dTransform.value = `translate(${cx - pos.faceX}px, ${cy - pos.faceY}px) scale(2.2)`
  }
}

// progress >= 50 时渐入 Live2D
const live2dShouldShow = computed(() => progress.value >= 50 && splashVisible.value)

function onSplashDismiss() {
  // 启用过渡动画
  live2dTransition.value = true
  // 回到正常位置
  live2dTransform.value = ''
  // 触发 SplashScreen 淡出
  splashVisible.value = false

  setTimeout(() => {
    showMainContent.value = true
  }, 200)

  setTimeout(() => {
    live2dTransition.value = false
    initialPositionSet = false
  }, 1500)
}

onMounted(() => {
  initParallax()
  startProgress()
})

onUnmounted(() => {
  destroyParallax()
  cleanup()
})
</script>

<template>
  <TitleBar />
  <div class="h-full sunflower" :style="{ paddingTop: isElectron ? '32px' : '0px' }">
    <!-- Live2D 层：启动时 z-10（在 SplashScreen 遮罩之间），之后降到 -z-1 -->
    <div
      class="absolute top-0 left-0 size-full"
      :class="splashVisible ? 'z-10' : '-z-1'"
      :style="{
        transform: live2dTransform,
        transition: live2dTransition ? 'transform 1.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.8s ease' : 'none',
        opacity: splashVisible ? (live2dShouldShow ? 1 : 0) : 1,
      }"
    >
      <img src="/assets/light.png" alt="" class="absolute right-0 bottom-0 w-80vw h-60vw op-40 -z-1 will-change-transform" :style="{ transform: `translate(${lightTx}px, ${lightTy}px)` }">
      <Live2dModel
        v-bind="CONFIG.web_live2d.model"
        :width="width" :height="height"
        :scale="scale" :ssaa="CONFIG.web_live2d.ssaa"
        @model-ready="onModelReady"
      />
    </div>

    <!-- 主内容区域 -->
    <Transition name="fade">
      <div v-if="showMainContent" class="h-full px-1/8 py-1/12 grid-container pointer-events-none">
        <RouterView v-slot="{ Component, route }">
          <Transition :name="route.path === '/' ? 'slide-out' : 'slide-in'">
            <component
              :is="Component"
              :key="route.fullPath"
              class="grid-item size-full pointer-events-auto"
            />
          </Transition>
        </RouterView>
      </div>
    </Transition>

    <!-- 启动界面遮罩（Transition 在父级控制淡出动画） -->
    <Transition name="splash-fade">
      <SplashScreen
        v-if="splashVisible"
        :progress="progress"
        :phase="phase"
        :model-ready="modelReady"
        @dismiss="onSplashDismiss"
      />
    </Transition>
  </div>
</template>

<style scoped>
.sunflower {
  border-image-source: url('/assets/sunflower.9.png');
  border-image-slice: 50%;
  border-image-width: 10em;
}

.grid-container {
  display: grid;
  grid-template-columns: 1fr;
}

.grid-item {
  grid-column: 1;
  grid-row: 1;
}

.slide-in-enter-from {
  transform: translateX(-100%);
}
.slide-in-leave-to {
  opacity: 0;
  transform: translate(-3%, -5%);
}

.slide-in-leave-active,
.slide-in-enter-active,
.slide-out-leave-active,
.slide-out-enter-active {
  transition: all 1s ease;
}

.slide-out-enter-from {
  opacity: 0;
  transform: translate(-3%, -5%);
}

.slide-out-leave-to {
  opacity: 0;
  transform: translateX(-100%);
}

/* 主内容淡入 */
.fade-enter-active {
  transition: opacity 0.8s ease;
}
.fade-enter-from {
  opacity: 0;
}

/* SplashScreen 淡出 */
.splash-fade-leave-active {
  transition: opacity 1s ease;
}
.splash-fade-leave-to {
  opacity: 0;
}
</style>
