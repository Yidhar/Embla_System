import { createApp } from 'vue'
import './style.css'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import 'virtual:uno.css'

const router = createRouter({
  history: createWebHistory(),
  routes: []
})

createApp(App).use(router).mount('#app')
