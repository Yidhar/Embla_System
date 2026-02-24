import type { RouteRecordRaw } from 'vue-router'

export const chatRoutes: RouteRecordRaw[] = [
  { path: '/chat', component: () => import('@/views/MessageView.vue') },
]
