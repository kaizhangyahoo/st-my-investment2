import React from 'react';
import { useAuth } from '../../hooks/useAuth';
import { LogOut, LineChart } from 'lucide-react';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();

  return (
    <header className="sticky top-0 z-40 bg-white/80 dark:bg-slate-900/80 backdrop-blur border-b border-slate-200 dark:border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-sm shadow-blue-500/20">
            <LineChart className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-bold text-slate-900 dark:text-slate-100 text-base leading-tight">Portfolio Analytics</h1>
            <span className="text-xs text-slate-500">FastAPI & React Dashboard</span>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          {user && (
            <div className="text-right hidden sm:block">
              <div className="text-sm font-medium text-slate-800 dark:text-slate-200">{user.name || user.email}</div>
              <div className="text-xs text-slate-400">{user.email}</div>
            </div>
          )}
          <button
            onClick={logout}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Sign out"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </div>
    </header>
  );
};

