import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

export default function Navbar() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/auth')
  }

  return (
    <header className="sticky top-0 z-50 bg-slate-900/80 backdrop-blur border-b border-slate-700">
      <nav className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">

        {/* 로고 */}
        <Link to="/dashboard" className="flex items-center gap-2 font-bold text-lg text-white">
          <span className="text-blue-400">📈</span>
          <span>InvestAI</span>
        </Link>

        {/* 메인 링크 */}
        <div className="flex items-center gap-6 text-sm text-slate-300">
          <Link to="/dashboard"
            className="hover:text-white transition-colors">
            포트폴리오
          </Link>
          <Link to="/supply-chain"
            className="hover:text-white transition-colors">
            공급망 지도
          </Link>
          {isAdmin && (
            <Link to="/admin"
              className="text-amber-400 hover:text-amber-300 transition-colors font-medium">
              관리자
            </Link>
          )}
        </div>

        {/* 사용자 정보 + 로그아웃 */}
        <div className="flex items-center gap-3 text-sm">
          <span className="text-slate-400 hidden sm:inline">
            {user?.full_name || user?.email}
          </span>
          {isAdmin && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
              ADMIN
            </span>
          )}
          <button
            onClick={handleLogout}
            className="px-3 py-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-700 transition-colors"
          >
            로그아웃
          </button>
        </div>
      </nav>
    </header>
  )
}
