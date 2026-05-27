// ── 인증 관련 타입 정의 ──────────────────────────────────────────────────────

export type UserRole = 'ADMIN' | 'USER'

export interface User {
  id: string
  email: string
  full_name: string | null
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
  phone_number?: string
}

/** JWT access token 디코드 페이로드 (python-jose HS256) */
export interface TokenPayload {
  sub: string     // user UUID
  role: UserRole
  type: 'access' | 'refresh'
  exp: number
}
