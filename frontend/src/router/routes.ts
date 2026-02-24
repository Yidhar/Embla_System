import type { RouteRecordRaw } from 'vue-router'
import { chatRoutes } from '@/domains/chat/routes'
import { opsRoutes } from '@/domains/ops/routes'
import { settingsRoutes } from '@/domains/settings/routes'
import { toolsRoutes } from '@/domains/tools/routes'

export const appRoutes: RouteRecordRaw[] = [
  ...opsRoutes,
  ...chatRoutes,
  ...settingsRoutes,
  ...toolsRoutes,
]
