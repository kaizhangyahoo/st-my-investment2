import React, { useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { Lock, Mail, ArrowRight } from 'lucide-react';

export const LoginForm: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [error, setError] = useState<string | null>(null);
  const { login, isLoading } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email || !password) {
      setError('Please provide both email and password');
      return;
    }
    const success = await login(email, password);
    if (!success) {
      setError('Invalid email or password');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#1a1a2e] via-[#16213e] to-[#0f3460] p-4">
      <div className="w-full max-w-md bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-8 shadow-2xl text-white">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold tracking-tight">Portfolio Analytics</h2>
          <p className="text-xs text-slate-300 mt-1">Sign in to manage your investment assets</p>
        </div>

        <div className="grid grid-cols-2 bg-white/5 p-1 rounded-xl mb-6">
          <button
            type="button"
            onClick={() => setMode('signin')}
            className={`py-1.5 text-xs font-semibold rounded-lg transition-all ${
              mode === 'signin' ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => setMode('signup')}
            className={`py-1.5 text-xs font-semibold rounded-lg transition-all ${
              mode === 'signup' ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
            }`}
          >
            Sign Up
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-500/20 border border-rose-500/30 text-rose-200 text-xs text-center">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Email</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-4 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-4 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full mt-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 rounded-xl transition-all shadow-lg shadow-blue-600/30 flex items-center justify-center text-sm disabled:opacity-50"
          >
            {isLoading ? 'Authenticating...' : mode === 'signin' ? 'Sign In' : 'Create Account'}
            <ArrowRight className="w-4 h-4 ml-1.5" />
          </button>
        </form>

        <div className="mt-8 pt-6 border-t border-white/10 text-center">
          <p className="text-xs text-slate-400">
            By signing in, you agree to our{' '}
            <a href="/legal" className="text-blue-400 hover:underline">
              Privacy Policy
            </a>
          </p>
        </div>
      </div>
    </div>
  );
};

