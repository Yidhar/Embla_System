<script setup lang="ts">
import { useToast } from 'primevue/usetoast'
import { computed, inject, ref } from 'vue'
import { useRouter } from 'vue-router'
import { isNagaLoggedIn, nagaUser, useAuth } from '@/composables/useAuth'

const toast = useToast()
const router = useRouter()
const { logout } = useAuth()
const menuOpen = ref(false)
const openLoginDialog = inject<() => void>('openLoginDialog')

function toggleMenu() {
  if (!isNagaLoggedIn.value) {
    // 未登录时点击打开登录弹窗
    openLoginDialog?.()
  }
  else {
    // 已登录时切换菜单
    menuOpen.value = !menuOpen.value
  }
}

function closeMenu() {
  menuOpen.value = false
}

function goConfig() {
  closeMenu()
  router.push('/config')
}

function openModelPlaza() {
  closeMenu()
  toast.add({ severity: 'info', summary: '功能开发中', detail: '模型广场功能即将上线', life: 3000 })
}

async function handleLogout() {
  closeMenu()
  await logout()
}

const initial = computed(() => {
  if (!isNagaLoggedIn.value) {
    return '?'
  }
  const name = nagaUser.value?.username ?? ''
  return name.charAt(0).toUpperCase()
})

const displayName = computed(() => {
  return isNagaLoggedIn.value ? nagaUser.value?.username : '未登录'
})
</script>

<template>
  <div class="user-menu" @mouseleave="closeMenu">
    <button class="avatar-btn" @click="toggleMenu">
      <span class="avatar" :class="{ 'not-logged-in': !isNagaLoggedIn }">{{ initial }}</span>
      <span class="username">{{ displayName }}</span>
    </button>
    <Transition name="dropdown-fade">
      <div v-if="menuOpen && isNagaLoggedIn" class="dropdown">
        <!-- 用户信息头部 -->
        <div class="user-header">
          <div class="user-header-name">{{ nagaUser?.username }}</div>
          <div v-if="nagaUser?.sub" class="user-header-id">ID: {{ nagaUser.sub }}</div>
        </div>
        <div class="dropdown-divider gold" />
        <button class="dropdown-item" @click="goConfig">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" /></svg>
          用户设置
        </button>
        <button class="dropdown-item" @click="openModelPlaza">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></svg>
          模型广场
        </button>
        <div class="dropdown-divider" />
        <button class="dropdown-item logout" @click="handleLogout">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
          登出
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.user-menu {
  position: relative;
  display: flex;
  align-items: center;
  height: 100%;
  -webkit-app-region: no-drag;
}

.avatar-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 100%;
  padding: 0 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.8);
  font-size: 12px;
  transition: background 0.15s;
}

.avatar-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}

.avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.9), rgba(180, 140, 30, 0.9));
  color: #1a1206;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar.not-logged-in {
  background: linear-gradient(135deg, rgba(150, 150, 150, 0.5), rgba(100, 100, 100, 0.5));
  color: rgba(255, 255, 255, 0.6);
}

.username {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  min-width: 180px;
  padding: 4px 0;
  background: rgba(30, 22, 10, 0.96);
  border: 1px solid rgba(212, 175, 55, 0.25);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  z-index: 100;
}

.user-header {
  padding: 10px 14px 8px;
}

.user-header-name {
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  font-weight: 600;
}

.user-header-id {
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
  margin-top: 2px;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 14px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.dropdown-item:hover {
  background: rgba(212, 175, 55, 0.1);
  color: rgba(212, 175, 55, 0.9);
}

.dropdown-item.logout:hover {
  background: rgba(232, 93, 93, 0.1);
  color: #e85d5d;
}

.dropdown-divider {
  height: 1px;
  margin: 4px 10px;
  background: rgba(255, 255, 255, 0.08);
}

.dropdown-divider.gold {
  background: linear-gradient(90deg, transparent, rgba(212, 175, 55, 0.35), transparent);
}

.dropdown-fade-enter-active {
  transition: opacity 0.15s, transform 0.15s;
}

.dropdown-fade-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.dropdown-fade-leave-active {
  transition: opacity 0.1s;
}

.dropdown-fade-leave-to {
  opacity: 0;
}
</style>
