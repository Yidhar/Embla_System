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
  ],
})

createApp(App).use(router).mount('#app')
