/**
 * AdminRoute — role=ADMIN 이 아닌 사용자는 대시보드로 리다이렉트
 * PrivateRoute 안에 중첩하여 사용:
 *   <Route element={<PrivateRoute />}>
 *     <Route element={<AdminRoute />}>
 *       <Route path="/admin" element={<AdminPage />} />
 *     </Route>
 *   </Route>
 */

import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function AdminRoute() {
  const { isAdmin } = useAuth()
  return isAdmin ? <Outlet /> : <Navigate to="/dashboard" replace />
}
