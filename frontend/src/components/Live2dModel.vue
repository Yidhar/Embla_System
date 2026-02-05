<script setup lang="ts">
import { Live2DModel } from 'pixi-live2d-display'
import * as PIXI from 'pixi.js'
import { computed, onMounted, onUnmounted, useTemplateRef, watch } from 'vue'

const props = withDefaults(defineProps<{
  model: string
  width: number
  height: number
  x?: number
  y?: number
  scale?: number
  factor?: number
}>(), {
  x: 0,
  y: 0,
  scale: 1,
  factor: 1,
})

Live2DModel.registerTicker(PIXI.Ticker)

let app: PIXI.Application
let model: Live2DModel & { rawWidth: number, rawHeight: number }

const computedScale = computed(() => props.scale * props.factor)
const computedWidth = computed(() => props.width * props.factor)
const computedHeight = computed(() => props.height * props.factor)
const computedX = computed(() => props.width * props.factor * (1 + props.x) - model.rawWidth * computedScale.value)
const computedY = computed(() => props.height * props.factor * (1 + props.y) - model.rawHeight * computedScale.value)

function initializeModel(model: Live2DModel) {
  watch(() => [computedWidth.value, computedHeight.value], app.resize)
  watch(computedScale, scale => model.scale.set(scale), { immediate: true })
  watch(computedX, x => model.x = x / 2, { immediate: true })
  watch(computedY, y => model.y = y / 2, { immediate: true })
}

const canvas = useTemplateRef('canvas')

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

  try {
    const rawModel = await Live2DModel.from(props.model)
    model = Object.assign(rawModel, {
      rawWidth: rawModel.width,
      rawHeight: rawModel.height,
    })
    initializeModel(model)
    app.stage.addChild(model)
  }
  catch (error) {
    console.error('Failed to initialize Live2D:', error)
  }
})

onUnmounted(() => app && app.destroy())
</script>

<template>
  <canvas ref="canvas" :width="computedWidth" :height="computedHeight" :style="{ zoom: 1 / factor }" />
</template>
