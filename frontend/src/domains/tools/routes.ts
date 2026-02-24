import type { RouteRecordRaw } from 'vue-router'

export const toolsRoutes: RouteRecordRaw[] = [
  { path: '/skill', component: () => import('@/views/SkillView.vue') },
]
