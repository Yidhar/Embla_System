/**
 * 预加载所有路由视图组件，与 main.ts 中 router 使用相同 import() 路径（Vite 自动去重）。
 * 串行 import 避免 Vite 冷启动时并发请求打满转换管线。
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
  for (let i = 0; i < total; i++) {
    try {
      await VIEW_IMPORTS[i]()
    } catch {
      // 加载失败不阻塞启动，后续导航时会重新加载
    }
    onProgress?.(i + 1, total)
  }
}
