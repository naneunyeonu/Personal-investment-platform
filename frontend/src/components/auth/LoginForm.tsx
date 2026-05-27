import { useState, type FormEvent } from 'react'
import { useAuth } from '../../context/AuthContext'

interface Props {
  onSuccess: () => void
  onSwitchToRegister: () => void
}

export default function LoginForm({ onSuccess, onSwitchToRegister }: Props) {
  const { login } = useAuth()

  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login({ email, password })
      onSuccess()
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? '로그인에 실패했습니다.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
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
        </label>
        <input
          type="password"
          required
          autoComplete="current-password"
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
        {loading ? '로그인 중…' : '로그인'}
      </button>

      <p className="text-center text-sm text-slate-400">
        계정이 없으신가요?{' '}
        <button
          type="button"
          onClick={onSwitchToRegister}
          className="text-blue-400 hover:text-blue-300 font-medium"
        >
          회원가입
        </button>
      </p>
    </form>
  )
}
