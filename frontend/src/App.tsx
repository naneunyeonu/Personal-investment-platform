/**
 * App — 라우팅 설정
 *
 * 라우트 구조:
 *   /                → /dashboard (리다이렉트)
 *   /auth            → AuthPage (로그인 / 회원가입)
 *   /dashboard       → DashboardPage     [PrivateRoute]
 *   /supply-chain    → SupplyChainPage   [PrivateRoute]
 *   /admin           → AdminPage (추후 구현)  [PrivateRoute + AdminRoute]
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import PrivateRoute from './routes/PrivateRoute'
import AdminRoute from './routes/AdminRoute'
import DashboardLayout from './components/layout/DashboardLayout'
import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import SupplyChainPage from './pages/SupplyChainPage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* 공개 라우트 */}
          <Route path="/auth" element={<AuthPage />} />

          {/* 인증 필요 라우트 */}
          <Route element={<PrivateRoute />}>
            <Route element={<DashboardLayout />}>
              <Route path="/dashboard"    element={<DashboardPage />} />
              <Route path="/supply-chain" element={<SupplyChainPage />} />

              {/* 관리자 전용 라우트 */}
              <Route element={<AdminRoute />}>
                <Route path="/admin" element={
                  <div className="flex items-center justify-center h-64">
                    <div className="text-center space-y-2">
                      <p className="text-2xl">🔐</p>
                      <p className="text-white font-semibold">관리자 대시보드</p>
                      <p className="text-slate-400 text-sm">사용자 관리 기능은 추후 구현 예정입니다.</p>
                    </div>
                  </div>
                } />
              </Route>
            </Route>
          </Route>

          {/* 루트 → 대시보드 리다이렉트 */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          {/* 404 → 대시보드 */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
