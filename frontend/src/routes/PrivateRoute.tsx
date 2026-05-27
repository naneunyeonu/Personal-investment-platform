/**
 * PrivateRoute — 비로그인 사용자를 /auth 로 리다이렉트
 * React Router v7 의 <Outlet> 패턴 사용
 */

import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function PrivateRoute() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return user ? <Outlet /> : <Navigate to="/auth" replace />
}
