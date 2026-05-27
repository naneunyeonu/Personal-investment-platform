/**
 * axios 인스턴스 — JWT Bearer 토큰 자동 첨부 + 401 시 자동 refresh
 *
 * 저장 전략:
 *   access_token  → sessionStorage (탭 닫으면 만료)
 *   refresh_token → localStorage   (브라우저 재시작 후에도 유지)
 */

import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from 'axios'

// ── 토큰 스토리지 헬퍼 ────────────────────────────────────────────────────

const ACCESS_KEY  = 'access_token'
const REFRESH_KEY = 'refresh_token'

export const tokenStorage = {
  getAccess:     () => sessionStorage.getItem(ACCESS_KEY),
  setAccess:     (t: string) => sessionStorage.setItem(ACCESS_KEY, t),
  getRefresh:    () => localStorage.getItem(REFRESH_KEY),
  setRefresh:    (t: string) => localStorage.setItem(REFRESH_KEY, t),
  clearAll:      () => {
    sessionStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
  saveTokens: (access: string, refresh: string) => {
    sessionStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
}

// ── axios 인스턴스 ─────────────────────────────────────────────────────────

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
})

// ── 요청 인터셉터: access_token 자동 첨부 ────────────────────────────────

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStorage.getAccess()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ── 응답 인터셉터: 401 → refresh → 재요청 ────────────────────────────────

let _refreshing = false
let _waitQueue: Array<(token: string) => void> = []

const processQueue = (token: string) => {
  _waitQueue.forEach(cb => cb(token))
  _waitQueue = []
}

api.interceptors.response.use(
  res => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error)
    }

    original._retry = true

    const refreshToken = tokenStorage.getRefresh()
    if (!refreshToken) {
      tokenStorage.clearAll()
      window.location.href = '/auth'
      return Promise.reject(error)
    }

    if (_refreshing) {
      // 이미 refresh 중이면 큐에 대기
      return new Promise(resolve => {
        _waitQueue.push((token: string) => {
          original.headers.Authorization = `Bearer ${token}`
          resolve(api(original))
        })
      })
    }

    _refreshing = true
    try {
      const { data } = await axios.post('/api/v1/auth/refresh', {
        refresh_token: refreshToken,
      })
      tokenStorage.saveTokens(data.access_token, data.refresh_token)
      processQueue(data.access_token)
      original.headers.Authorization = `Bearer ${data.access_token}`
      return api(original)
    } catch {
      tokenStorage.clearAll()
      window.location.href = '/auth'
      return Promise.reject(error)
    } finally {
      _refreshing = false
    }
  }
)
