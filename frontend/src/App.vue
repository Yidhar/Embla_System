<script setup lang="ts">
import { useWindowSize } from '@vueuse/core'
import { computed } from 'vue'
import Live2dModel from '@/components/Live2dModel.vue'

const MODELS = {
  NagaTest: ['/models/live2d-naga/naga-test.model3.json', 0.5, 0.7, 4500],
  重音テト: ['/models/重音テト/重音テト.model3.json', 0.5, 0, 8000],
} as const

const [model, x, y, size] = MODELS.重音テト
const { width, height } = useWindowSize()
const scale = computed(() => height.value / size)
</script>

<template>
  <div class="h-full sunflower">
    <div class="absolute top-0 left-0 size-full -z-1">
      <img src="/assets/light.png" alt="" class="absolute right-0 bottom-0 w-80vw h-60vw op-40 -z-1">
      <Live2dModel :model="model" :width="width" :height="height" :x="x" :y="y" :scale="scale" :factor="2" />
    </div>
    <router-view class="h-full" />
  </div>
</template>

<style scoped>
.sunflower {
  border-image-source: url('/assets/sunflower.9.png');
  border-image-slice: 50%;
  border-image-width: 10em;
}
</style>
