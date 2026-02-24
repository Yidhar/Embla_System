import type { RouteRecordRaw } from 'vue-router'

export const settingsRoutes: RouteRecordRaw[] = [
  { path: '/model', component: () => import('@/views/ModelView.vue') },
  { path: '/memory', component: () => import('@/views/MemoryView.vue') },
  { path: '/config', component: () => import('@/views/ConfigView.vue') },
]
