/**
 * axios 인스턴스 — JWT Bearer 토큰 자동 첨부 + 401 시 자동 refresh
 *
 * 저장 전략:
 *   access_token  → sessionStorage (탭 닫으면 만료)
 *   refresh_token → localStorage   (브라우저 재시작 후에도 유지)
 *
 * Refresh 플로우:
 *   1. 요청 → 401 수신
 *   2. refresh_token 없으면 → 즉시 /auth 이동
 *   3. 이미 refresh 중이면 → _waitQueue에 적재 (중복 refresh 방지)
 *   4. refresh 성공 → access_token 갱신 + 큐에 대기 중이던 요청 일괄 재전송
 *   5. refresh 실패 → 큐 전체 reject + 토큰 삭제 + /auth 이동
 *
 * 무한 루프 방지:
 *   - /auth/refresh 엔드포인트 자체가 401 반환 시 즉시 logout (재시도 없음)
 *   - original._retry 플래그로 단일 요청 중복 재시도 차단
 */

import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from 'axios'

// ── 토큰 스토리지 헬퍼 ────────────────────────────────────────────────────

const ACCESS_KEY  = 'access_token'
const REFRESH_KEY = 'refresh_token'

export const tokenStorage = {
  getAccess:  () => sessionStorage.getItem(ACCESS_KEY),
  setAccess:  (t: string) => sessionStorage.setItem(ACCESS_KEY, t),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  setRefresh: (t: string) => localStorage.setItem(REFRESH_KEY, t),
  clearAll: () => {
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

/**
 * 대기 큐 아이템: refresh 완료 시 resolve(newToken) 또는 reject(error) 호출
 */
interface _QueueItem {
  resolve: (token: string) => void
  reject:  (error: unknown) => void
}

let _refreshing = false
let _waitQueue: _QueueItem[] = []

/**
 * 큐에 대기 중인 모든 요청을 일괄 처리.
 * @param token 새 access_token (성공 시)
 * @param error 오류 (실패 시) — null이 아니면 모두 reject
 */
const processQueue = (token: string | null, error: unknown = null): void => {
  _waitQueue.forEach(({ resolve, reject }) => {
    if (error !== null || token === null) {
      reject(error)
    } else {
      resolve(token)
    }
  })
  _waitQueue = []
}

/**
 * 토큰 삭제 후 로그인 페이지로 강제 이동.
 */
const forceLogout = (): void => {
  tokenStorage.clearAll()
  window.location.href = '/auth'
}

api.interceptors.response.use(
  res => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // ── 401 이외의 오류 → 그대로 전파 ──────────────────────────────────
    if (error.response?.status !== 401) {
      return Promise.reject(error)
    }

    // ── 무한 루프 방지: refresh 엔드포인트 자체가 401인 경우 ─────────────
    // POST /api/v1/auth/refresh 요청이 401을 반환했다면 refresh_token도 만료.
    // 재시도 없이 즉시 로그아웃.
    if (original.url?.includes('/auth/refresh')) {
      processQueue(null, error)
      forceLogout()
      return Promise.reject(error)
    }

    // ── 이미 재시도한 요청 → 무한 루프 방지 ────────────────────────────
    if (original._retry) {
      return Promise.reject(error)
    }

    original._retry = true

    // ── refresh_token 없으면 즉시 로그아웃 ──────────────────────────────
    const refreshToken = tokenStorage.getRefresh()
    if (!refreshToken) {
      forceLogout()
      return Promise.reject(error)
    }

    // ── 이미 refresh 중이면 큐에 적재하여 완료 후 재전송 ────────────────
    if (_refreshing) {
      return new Promise((resolve, reject) => {
        _waitQueue.push({
          resolve: (newToken: string) => {
            original.headers.Authorization = `Bearer ${newToken}`
            resolve(api(original))
          },
          reject,
        })
      })
    }

    // ── refresh 요청 실행 ────────────────────────────────────────────────
    _refreshing = true
    try {
      // axios 인스턴스가 아닌 기본 axios 사용
      // → 이 요청 자체에 인터셉터 적용되지 않도록 (재귀 방지)
      const { data } = await axios.post('/api/v1/auth/refresh', {
        refresh_token: refreshToken,
      })

      tokenStorage.saveTokens(data.access_token, data.refresh_token)

      // 대기 중인 요청 모두 새 토큰으로 재전송
      processQueue(data.access_token)

      original.headers.Authorization = `Bearer ${data.access_token}`
      return api(original)

    } catch (refreshError) {
      // refresh 실패 → 대기 큐 전체 reject → 로그아웃
      processQueue(null, refreshError)
      forceLogout()
      return Promise.reject(refreshError)

    } finally {
      _refreshing = false
    }
  }
)
