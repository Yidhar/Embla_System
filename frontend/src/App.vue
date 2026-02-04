<script setup lang="ts">
import { useWindowSize } from '@vueuse/core';
import MessageInput from './components/MessageInput.vue'
import MessageView from './components/MessageView.vue'
import Live2dModel from './components/Live2dModel.vue'

// const model = "/models/live2d-naga/naga-test.model3.json"
const model = "/models/重音テト/重音テト.model3.json"
const { width, height } = useWindowSize()
</script>

<template>
    <div class="h-full sunflower px-42 py-4">
        <div class="fixed top-0 left-0 w-full h-full -z-1">
            <img src="/assets/light.png" alt="" class="absolute right-0 bottom-0 w-80vw h-60vw op-40 -z-2">
            <Live2dModel :model="model" :width="width" :height="height" />
        </div>
        <div class="h-full flex flex-col items-center justify-center gap-8">
            <div class="w-full grow grid grid-cols-2">
                <MessageView class="w-full" />
            </div>
            <MessageInput class="w-full" />
        </div>
    </div>
</template>

<style scoped>
.sunflower {
    border-image-source: url('/assets/sunflower.9.png');
    border-image-slice: 50%;
    border-image-width: 10em;
}
</style>
