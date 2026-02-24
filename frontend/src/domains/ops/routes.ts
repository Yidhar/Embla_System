import type { RouteRecordRaw } from 'vue-router'

export const opsRoutes: RouteRecordRaw[] = [
  { path: '/', component: () => import('@/views/PanelView.vue') },
  { path: '/mind', component: () => import('@/views/MindView.vue') },
]
