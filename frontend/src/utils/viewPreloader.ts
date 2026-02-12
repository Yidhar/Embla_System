/**
 * 预加载所有路由视图组件，与 main.ts 中 router 使用相同 import() 路径（Vite 自动去重）。
 */
const VIEW_IMPORTS = [
  () => import('@/views/PanelView.vue'),
  () => import('@/views/MessageView.vue'),
  () => import('@/views/ModelView.vue'),
  () => import('@/views/MemoryView.vue'),
  () => import('@/views/MindView.vue'),
  () => import('@/views/SkillView.vue'),
  () => import('@/views/ConfigView.vue'),
]

export async function preloadAllViews(
  onProgress?: (loaded: number, total: number) => void,
): Promise<void> {
  const total = VIEW_IMPORTS.length
  let loaded = 0

  const tasks = VIEW_IMPORTS.map(loader =>
    loader().then(() => {
      loaded++
      onProgress?.(loaded, total)
    }).catch(() => {
      // 加载失败不阻塞启动，后续导航时会重新加载
      loaded++
      onProgress?.(loaded, total)
    }),
  )

  await Promise.allSettled(tasks)
}
