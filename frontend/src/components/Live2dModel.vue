<script lang="ts">
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import * as PIXI from 'pixi.js'
import { computed, nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import { destroyController, initController, startTracking, stopTracking, updateTracking } from '@/utils/live2dController'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}
window.PIXI = PIXI
</script>

<script setup lang="ts">
const { source, width, height, x, y, scale, ssaa } = defineProps<{
  source: string
  width: number
  height: number
  x: number
  y: number
  scale: number
  ssaa: number
}>()

let app: PIXI.Application

const computedScale = computed(() => scale * ssaa)
const computedWidth = computed(() => width * ssaa)
const computedHeight = computed(() => height * ssaa)

const canvas = useTemplateRef('canvas')
const isDragging = ref(false)

function onPointerDown(e: PointerEvent) {
  isDragging.value = true
  ;(e.target as Element).setPointerCapture(e.pointerId)
  startTracking()
  updateTrackingFromEvent(e)
}

function onPointerMove(e: PointerEvent) {
  if (!isDragging.value) return
  updateTrackingFromEvent(e)
}

function onPointerUp(e: PointerEvent) {
  if (!isDragging.value) return
  isDragging.value = false
  ;(e.target as Element).releasePointerCapture(e.pointerId)
  stopTracking()
}

function updateTrackingFromEvent(e: PointerEvent) {
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const normalizedX = ((e.clientX - rect.left) / rect.width) * 2 - 1
  const normalizedY = ((e.clientY - rect.top) / rect.height) * 2 - 1
  updateTracking(normalizedX, normalizedY)
}

onMounted(async () => {
  if (!canvas.value)
    return

  app = new PIXI.Application({
    view: canvas.value,
    width: computedWidth.value,
    height: computedHeight.value,
    antialias: true,
    backgroundAlpha: 0,
    resizeTo: canvas.value,
  })

  watch(() => [width, height, ssaa], () => nextTick().then(() => app.resize()))

  watch(() => source, async (source, _, onCleanUp) => {
    try {
      const rawModel = await Live2DModel.from(source)
      const model = Object.assign(rawModel, {
        rawWidth: rawModel.width,
        rawHeight: rawModel.height,
      })

      const computedX = computed(() => width * ssaa * (1 + x) - model.rawWidth * computedScale.value)
      const computedY = computed(() => height * ssaa * (1 + y) - model.rawHeight * computedScale.value)

      const handles = [
        watch(computedScale, scale => model.scale.set(scale), { immediate: true }),
        watch(computedX, x => model.x = x / 2, { immediate: true }),
        watch(computedY, y => model.y = y / 2, { immediate: true }),
      ]

      model.autoInteract = false
      app.stage.addChild(model)
      initController(rawModel)

      onCleanUp(() => {
        destroyController()
        app.stage.removeChild(model)
        model.destroy()
        handles.forEach(handle => handle.stop())
      })
    }
    catch (error) {
      console.error('Failed to initialize Live2D:', error)
    }
  }, { immediate: true })
})

onUnmounted(() => app && app.destroy())
</script>

<template>
  <canvas
    ref="canvas"
    :width="computedWidth" :height="computedHeight"
    :style="{ zoom: 1 / ssaa, touchAction: 'none' }"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointerleave="onPointerUp"
  />
</template>
