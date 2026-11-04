import { create } from 'zustand';
import { UserProfile } from '../types';
import { authApi } from '../services/api';

interface AuthState {
  user: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem('access_token'),
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: false,

  login: async (email, password) => {
    try {
      set({ isLoading: true });
      const res = await authApi.login(email, password);
      if (res.access_token) {
        localStorage.setItem('access_token', res.access_token);
        set({
          token: res.access_token,
          user: { email: res.email || email, name: res.display_name, provider: 'email', user_id: res.user_id },
          isAuthenticated: true,
          isLoading: false,
        });
        return true;
      }
      set({ isLoading: false });
      return false;
    } catch (err) {
      set({ isLoading: false });
      return false;
    }
  },

  logout: () => {
    localStorage.removeItem('access_token');
    set({ user: null, token: null, isAuthenticated: false });
  },

  checkAuth: async () => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    try {
      const user = await authApi.getMe();
      set({ user, isAuthenticated: true });
    } catch {
      localStorage.removeItem('access_token');
      set({ user: null, token: null, isAuthenticated: false });
    }
  },
}));

