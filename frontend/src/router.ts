import { createRouter, createWebHistory } from 'vue-router'

import { loadAccessToken } from '@/lib/api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/pages/HomePage.vue') },
    { path: '/login', component: () => import('@/pages/LoginPage.vue') },
    { path: '/register', component: () => import('@/pages/RegisterPage.vue') },
    { path: '/workspace', component: () => import('@/pages/WorkspacePage.vue'), meta: { requiresAuth: true } },
    { path: '/score', component: () => import('@/pages/ScorePage.vue'), meta: { requiresAuth: true } },
    { path: '/risk', component: () => import('@/pages/RiskPage.vue'), meta: { requiresAuth: true } },
    { path: '/verify', component: () => import('@/pages/VerifyPage.vue'), meta: { requiresAuth: true } },
    { path: '/admin', component: () => import('@/pages/AdminPage.vue'), meta: { requiresAuth: true } },
    { path: '/evidence/:chunkId', component: () => import('@/pages/EvidencePage.vue'), props: true, meta: { requiresAuth: true } },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  const isAuthenticated = Boolean(loadAccessToken())
  if (to.meta.requiresAuth && !isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (isAuthenticated && (to.path === '/login' || to.path === '/register')) {
    return { path: '/workspace' }
  }
  return true
})

export default router
