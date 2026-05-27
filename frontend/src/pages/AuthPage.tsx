/**
 * AuthPage — 로그인 / 회원가입 통합 페이지
 *
 * 탭 토글로 LoginForm ↔ RegisterForm 전환.
 * 로그인/가입 성공 시 /dashboard 로 이동.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import LoginForm from '../components/auth/LoginForm'
import RegisterForm from '../components/auth/RegisterForm'

export default function AuthPage() {
  const [tab, setTab]               = useState<'login' | 'register'>('login')
  const [registered, setRegistered] = useState(false)
  const navigate = useNavigate()

  const handleLoginSuccess = () => navigate('/dashboard', { replace: true })

  const handleRegisterSuccess = () => {
    setRegistered(true)
    setTab('login')
  }

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center px-4">

      {/* 카드 */}
      <div className="w-full max-w-md">

        {/* 브랜드 헤더 */}
        <div className="text-center mb-8">
          <span className="text-5xl">📈</span>
          <h1 className="mt-3 text-3xl font-bold text-white">InvestAI</h1>
          <p className="mt-1 text-slate-400 text-sm">
            AI 기반 개인 투자 서포트 플랫폼
          </p>
        </div>

        {/* 회원가입 성공 알림 */}
        {registered && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-green-500/15 border border-green-500/30 text-green-400 text-sm">
            ✅ 회원가입이 완료되었습니다. 로그인해 주세요.
          </div>
        )}

        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-8 shadow-2xl">

          {/* 탭 */}
          <div className="flex rounded-lg bg-slate-900 p-1 mb-6">
            {(['login', 'register'] as const).map(t => (
              <button
                key={t}
                onClick={() => { setTab(t); setRegistered(false) }}
                className={`flex-1 py-2 rounded-md text-sm font-medium transition-all ${
                  tab === t
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {t === 'login' ? '로그인' : '회원가입'}
              </button>
            ))}
          </div>

          {/* 폼 */}
          {tab === 'login' ? (
            <LoginForm
              onSuccess={handleLoginSuccess}
              onSwitchToRegister={() => setTab('register')}
            />
          ) : (
            <RegisterForm
              onSuccess={handleRegisterSuccess}
              onSwitchToLogin={() => setTab('login')}
            />
          )}
        </div>

        <p className="text-center text-xs text-slate-600 mt-6">
          이 플랫폼은 투자 분석 지원 목적으로만 사용됩니다. 실제 매수/매도 기능은 제공하지 않습니다.
        </p>
      </div>
    </div>
  )
}
