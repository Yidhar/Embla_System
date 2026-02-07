<script setup lang="ts">
import { useWindowSize } from '@vueuse/core'
import { computed } from 'vue'
import Live2dModel from '@/components/Live2dModel.vue'

const MODELS = {
  NagaTest: ['/models/live2d-naga/naga-test.model3.json', 0.5, 1.3, 3200],
  重音テト: ['/models/重音テト/重音テト.model3.json', 0.5, 0.8, 4500],
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
    <div class="h-full px-1/8 py-1/12 grid-container">
      <RouterView v-slot="{ Component, route }">
        <Transition :name="route.path === '/' ? 'slide-out' : 'slide-in'">
          <component
            :is="Component"
            :key="route.fullPath"
            class="grid-item size-full"
          />
        </Transition>
      </RouterView>
    </div>
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
</style>
