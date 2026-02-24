import { definePreset } from '@primeuix/themes'
import Lara from '@primeuix/themes/lara'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import { createApp } from 'vue'

import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import 'virtual:uno.css'
import { appRoutes } from '@/router/routes'

const router = createRouter({
  history: createWebHashHistory(),
  routes: appRoutes,
})

createApp(App)
  .use(PrimeVue, {
    theme: {
      preset: definePreset(Lara),
      options: {
        darkModeSelector: '.p-dark',
      },
    },
  })
  .use(ToastService)
  .use(router)
  .mount('#app')
