<script setup lang="ts">
import { onMounted, onUnmounted, useTemplateRef, watch } from 'vue'
import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display'

Live2DModel.registerTicker(PIXI.Ticker)

const props = withDefaults(defineProps<{
  model: string
  width: number
  height: number
  factor?: number
  alpha?: number
}>(), {
  factor: 2,
  alpha: 0,
})

let app: PIXI.Application
let model: Live2DModel

const container = useTemplateRef('container')

function initializeModel(model: Live2DModel) {
  model.scale.set(0.2 * props.factor)
  watch(() => props.width, (width) => model.x = (width * props.factor * 1.5 - model.width) / 2, { immediate: true })
  watch(() => props.height, (height) => model.y = (height * props.factor * 1.6 - model.height) / 2, { immediate: true })
}

onMounted(async () => {
  app = new PIXI.Application({
    view: container.value!,
    width: props.width * props.factor,
    height: props.height * props.factor,
    antialias: true,
    backgroundAlpha: props.alpha
  })

  try {
    model = await Live2DModel.from(props.model)
    initializeModel(model)
    app.stage.addChild(model)
  } catch (error) {
    console.error('Failed to initialize Live2D:', error)
  }
})

onUnmounted(() => app && app.destroy())
</script>

<template>
  <canvas ref="container" :style="{ zoom: 1 / factor }" />
</template>
