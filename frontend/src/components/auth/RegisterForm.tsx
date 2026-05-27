import { useState, type FormEvent } from 'react'
import { register as apiRegister } from '../../api/auth'

interface Props {
  onSuccess: () => void
  onSwitchToLogin: () => void
}

export default function RegisterForm({ onSuccess, onSwitchToLogin }: Props) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await apiRegister({ email, password, full_name: fullName || undefined })
      onSuccess()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail
      setError(
        typeof detail === 'string'
          ? detail
          : '회원가입에 실패했습니다. 다시 시도해 주세요.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          이름 (선택)
        </label>
        <input
          type="text"
          autoComplete="name"
          value={fullName}
          onChange={e => setFullName(e.target.value)}
          placeholder="홍길동"
          className="w-full px-4 py-2.5 rounded-lg bg-slate-700 border border-slate-600
                     text-white placeholder-slate-400 focus:outline-none focus:ring-2
                     focus:ring-blue-500 focus:border-transparent transition"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          이메일
        </label>
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full px-4 py-2.5 rounded-lg bg-slate-700 border border-slate-600
                     text-white placeholder-slate-400 focus:outline-none focus:ring-2
                     focus:ring-blue-500 focus:border-transparent transition"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1.5">
          비밀번호
          <span className="text-slate-500 font-normal ml-1.5">
            (영문+숫자 8자 이상)
          </span>
        </label>
        <input
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="••••••••"
          className="w-full px-4 py-2.5 rounded-lg bg-slate-700 border border-slate-600
                     text-white placeholder-slate-400 focus:outline-none focus:ring-2
                     focus:ring-blue-500 focus:border-transparent transition"
        />
      </div>

      {error && (
        <p className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-60
                   text-white font-semibold transition-colors"
      >
        {loading ? '가입 중…' : '회원가입'}
      </button>

      <p className="text-center text-sm text-slate-400">
        이미 계정이 있으신가요?{' '}
        <button
          type="button"
          onClick={onSwitchToLogin}
          className="text-blue-400 hover:text-blue-300 font-medium"
        >
          로그인
        </button>
      </p>
    </form>
  )
}
