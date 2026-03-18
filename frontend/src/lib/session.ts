import { computed, ref } from 'vue'

import { clearAuth, loadCurrentUser, type AuthUser } from '@/lib/api'

const currentUser = ref<AuthUser | null>(loadCurrentUser())

export function useSession() {
  const isAuthenticated = computed(() => currentUser.value !== null)

  function setUser(user: AuthUser | null) {
    currentUser.value = user
  }

  function logout() {
    clearAuth()
    currentUser.value = null
  }

  return {
    currentUser,
    isAuthenticated,
    setUser,
    logout,
  }
}
