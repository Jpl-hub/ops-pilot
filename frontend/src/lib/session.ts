import { computed, ref } from 'vue'

import { clearAuth, loadCurrentUser, type AuthUser, type UserRole } from '@/lib/api'
import { clearWorkflowContext } from '@/lib/workflowContext'

const currentUser = ref<AuthUser | null>(loadCurrentUser())
const ROLE_KEY = 'ops-pilot-active-role'
const activeRole = ref<UserRole>(loadActiveRole())

function loadActiveRole(): UserRole {
  const raw = localStorage.getItem(ROLE_KEY)
  if (raw === 'investor' || raw === 'management' || raw === 'regulator') {
    return raw
  }
  const user = loadCurrentUser()
  return user?.role || 'investor'
}

export function useSession() {
  const isAuthenticated = computed(() => currentUser.value !== null)

  function setUser(user: AuthUser | null) {
    currentUser.value = user
    if (user) {
      if (!localStorage.getItem(ROLE_KEY)) {
        setActiveRole(user.role || 'investor')
      }
      return
    }
    localStorage.removeItem(ROLE_KEY)
    activeRole.value = 'investor'
    clearWorkflowContext()
  }

  function setActiveRole(role: UserRole) {
    activeRole.value = role
    localStorage.setItem(ROLE_KEY, role)
  }

  function logout() {
    clearAuth()
    currentUser.value = null
    localStorage.removeItem(ROLE_KEY)
    activeRole.value = 'investor'
    clearWorkflowContext()
  }

  return {
    currentUser,
    activeRole,
    isAuthenticated,
    setUser,
    setActiveRole,
    logout,
  }
}
