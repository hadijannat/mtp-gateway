import { useState, type FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock, User, AlertCircle, Loader2 } from 'lucide-react';
import { useAuthStore } from '../store/authStore';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isLoading, error, clearError } = useAuthStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Get redirect path from location state, default to dashboard
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? '/';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    clearError();

    const success = await login({ username, password });
    if (success) {
      navigate(from, { replace: true });
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary">
      <div className="w-full max-w-md p-8">
        {/* Logo / Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-accent-primary/20 mb-4">
            <Lock className="w-8 h-8 text-accent-primary" />
          </div>
          <h1 className="text-2xl font-bold text-text-primary">MTP Gateway</h1>
          <p className="text-text-secondary mt-2">Industrial Control Interface</p>
        </div>

        {/* Login Form */}
        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 p-3 rounded bg-status-alarm/20 border border-status-alarm/30 text-status-alarm">
                <AlertCircle className="w-5 h-5 flex-shrink-0" />
                <span className="text-sm">{error}</span>
              </div>
            )}

            {/* Username */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-text-secondary mb-2">
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-muted" />
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input w-full pl-10"
                  placeholder="Enter username"
                  required
                  autoComplete="username"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-text-secondary mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-muted" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input w-full pl-10"
                  placeholder="Enter password"
                  required
                  autoComplete="current-password"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading || !username || !password}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          {/* Demo credentials hint */}
          <div className="mt-6 pt-6 border-t border-border-default">
            <p className="text-xs text-text-muted text-center">
              Demo credentials: operator / operator123
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-text-muted text-xs mt-8">
          VDI/VDE/NAMUR 2658 Compliant
        </p>
      </div>
    </div>
  );
}
