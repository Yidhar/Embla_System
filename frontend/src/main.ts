import { definePreset } from '@primeuix/themes'
import Nora from '@primeuix/themes/nora'
import PrimeVue from 'primevue/config'
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import 'virtual:uno.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/views/PanelView.vue') },
    { path: '/chat', component: () => import('@/views/MessageView.vue') },
    { path: '/model', component: () => import('@/views/ModelView.vue') },
    { path: '/memory', component: () => import('@/views/MemoryView.vue') },
    { path: '/mind', component: () => import('@/views/MindView.vue') },
    { path: '/tool', component: () => import('@/views/ToolView.vue') },
    { path: '/config', component: () => import('@/views/ConfigView.vue') },
  ],
})

// const primary = 'indigo'

createApp(App)
  .use(PrimeVue, {
    theme: {
      preset: definePreset(Nora, {
        semantic: {
          // primary: {
          //   50: `{${primary}.50}`,
          //   100: `{${primary}.100}`,
          //   200: `{${primary}.200}`,
          //   300: `{${primary}.300}`,
          //   400: `{${primary}.400}`,
          //   500: `{${primary}.500}`,
          //   600: `{${primary}.600}`,
          //   700: `{${primary}.700}`,
          //   800: `{${primary}.800}`,
          //   900: `{${primary}.900}`,
          //   950: `{${primary}.950}`,
          // },
        },
      }),
      options: {
        darkModeSelector: '.p-dark',
      },
    },
  })
  .use(router)
  .mount('#app')
