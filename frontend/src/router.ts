import { createRouter, createWebHistory } from 'vue-router'

import { loadAccessToken } from '@/lib/api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/pages/HomePage.vue') },
    { path: '/login', component: () => import('@/pages/LoginPage.vue') },
    { path: '/register', component: () => import('@/pages/RegisterPage.vue') },
    { path: '/brain', component: () => import('@/pages/IndustryBrainPage.vue'), meta: { requiresAuth: true } },
    { path: '/workspace', component: () => import('@/pages/WorkspacePage.vue'), meta: { requiresAuth: true } },
    { path: '/graph', component: () => import('@/pages/GraphPage.vue'), meta: { requiresAuth: true } },
    { path: '/stress', component: () => import('@/pages/StressPage.vue'), meta: { requiresAuth: true } },
    { path: '/vision', component: () => import('@/pages/VisionPage.vue'), meta: { requiresAuth: true } },
    { path: '/score', component: () => import('@/pages/ScorePage.vue'), meta: { requiresAuth: true } },
    { path: '/risk', component: () => import('@/pages/RiskPage.vue'), meta: { requiresAuth: true } },
    { path: '/verify', component: () => import('@/pages/VerifyPage.vue'), meta: { requiresAuth: true } },
    { path: '/profile', component: () => import('@/pages/ProfilePage.vue'), meta: { requiresAuth: true } },
    { path: '/admin', component: () => import('@/pages/AdminPage.vue'), meta: { requiresAuth: true } },
    { path: '/evidence/:chunkId', component: () => import('@/pages/EvidencePage.vue'), props: true, meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', component: () => import('@/pages/NotFoundPage.vue') },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  const isAuthenticated = Boolean(loadAccessToken())
  if (isAuthenticated && to.path === '/') {
    return { path: '/workspace' }
  }
  if (to.meta.requiresAuth && !isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (isAuthenticated && (to.path === '/login' || to.path === '/register')) {
    return { path: '/workspace' }
  }
  return true
})

export default router
