import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/pages/HomePage.vue') },
    { path: '/score', component: () => import('@/pages/ScorePage.vue') },
    { path: '/risk', component: () => import('@/pages/RiskPage.vue') },
    { path: '/verify', component: () => import('@/pages/VerifyPage.vue') },
    { path: '/admin', component: () => import('@/pages/AdminPage.vue') },
    { path: '/evidence/:chunkId', component: () => import('@/pages/EvidencePage.vue'), props: true },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
