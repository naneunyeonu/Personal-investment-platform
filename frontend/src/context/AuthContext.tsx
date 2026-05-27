/**
 * AuthContext — JWT 기반 인증 상태 전역 관리
 *
 * 제공 값:
 *   user        현재 로그인된 사용자 (null이면 비로그인)
 *   isAdmin     role === 'ADMIN'
 *   isLoading   초기 토큰 검증 중 여부 (스플래시 화면용)
 *   login()     로그인 → 토큰 저장 → user 갱신
 *   logout()    토큰 삭제 → user = null
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

import { tokenStorage } from '../api/client'
import { getMe, login as apiLogin } from '../api/auth'
import type { LoginRequest, TokenResponse, User } from '../types/auth'

// ── Context 타입 ──────────────────────────────────────────────────────────

interface AuthContextValue {
  user: User | null
  isAdmin: boolean
  isLoading: boolean
  login: (data: LoginRequest) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]         = useState<User | null>(null)
  const [isLoading, setLoading] = useState(true)

  /** 앱 초기 마운트 시 — 저장된 토큰으로 사용자 정보 복원 */
  useEffect(() => {
    const restore = async () => {
      const access = tokenStorage.getAccess()
      if (!access) {
        setLoading(false)
        return
      }
      try {
        const me = await getMe()
        setUser(me)
      } catch {
        tokenStorage.clearAll()
      } finally {
        setLoading(false)
      }
    }
    restore()
  }, [])

  const login = useCallback(async (data: LoginRequest) => {
    const tokens: TokenResponse = await apiLogin(data)
    tokenStorage.saveTokens(tokens.access_token, tokens.refresh_token)
    const me = await getMe()
    setUser(me)
  }, [])

  const logout = useCallback(() => {
    tokenStorage.clearAll()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        isAdmin: user?.role === 'ADMIN',
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
