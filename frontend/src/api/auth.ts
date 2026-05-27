import { api } from './client'
import type { LoginRequest, RegisterRequest, TokenResponse, User } from '../types/auth'

/** 회원가입 */
export const register = (data: RegisterRequest): Promise<User> =>
  api.post<User>('/auth/register', data).then(r => r.data)

/** 로그인 → JWT 토큰 반환 */
export const login = (data: LoginRequest): Promise<TokenResponse> =>
  api.post<TokenResponse>('/auth/login', data).then(r => r.data)

/** 내 계정 정보 조회 (access token 필요) */
export const getMe = (): Promise<User> =>
  api.get<User>('/auth/me').then(r => r.data)
