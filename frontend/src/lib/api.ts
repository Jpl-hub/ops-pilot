export const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
export const WS_BASE = import.meta.env.VITE_WS_BASE_URL || API_BASE
const TOKEN_KEY = 'ops-pilot-access-token'
const USER_KEY = 'ops-pilot-user'

export type UserRole = 'investor' | 'management' | 'regulator'

export interface AuthUser {
  user_id: string
  username: string
  display_name: string
  role: UserRole
  created_at: string
  last_login_at: string | null
}

export interface AuthPayload {
  access_token: string
  token_type: 'bearer'
  user: AuthUser
}

function parseErrorDetail(detail: string, status: number): string {
  if (!detail) return `请求失败：${status}`
  try {
    const payload = JSON.parse(detail) as { detail?: string }
    if (typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail
    }
  } catch {
    // fall through and keep raw detail
  }
  return detail
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = loadAccessToken()
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    ...init,
  })
  if (!response.ok) {
    if (response.status === 401) {
      clearAuth()
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/register')) {
        window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
      }
    }
    const detail = await response.text()
    throw new Error(parseErrorDetail(detail, response.status))
  }
  return response.json() as Promise<T>
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const token = loadAccessToken()
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    ...init,
  })
  if (!response.ok) {
    if (response.status === 401) {
      clearAuth()
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/register')) {
        window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
      }
    }
    const detail = await response.text()
    throw new Error(parseErrorDetail(detail, response.status))
  }
  return response.text()
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export function getText(path: string): Promise<string> {
  return requestText(path)
}

export function saveAuth(payload: AuthPayload) {
  localStorage.setItem(TOKEN_KEY, payload.access_token)
  localStorage.setItem(USER_KEY, JSON.stringify(payload.user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function loadAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function loadCurrentUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    clearAuth()
    return null
  }
}

export function buildWebSocketUrl(path: string): string {
  if (
    WS_BASE.startsWith('ws://') ||
    WS_BASE.startsWith('wss://') ||
    WS_BASE.startsWith('http://') ||
    WS_BASE.startsWith('https://')
  ) {
    const base = new URL(WS_BASE)
    const protocol =
      base.protocol === 'https:' ? 'wss:' : base.protocol === 'http:' ? 'ws:' : base.protocol
    return `${protocol}//${base.host}${base.pathname}${path}`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${WS_BASE}${path}`
}
