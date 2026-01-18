import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { authApi } from '../api';
import type { User, LoginRequest } from '../types';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions
  login: (credentials: LoginRequest) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      login: async (credentials: LoginRequest): Promise<boolean> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authApi.login(credentials);

          // Store tokens
          localStorage.setItem('access_token', response.access_token);
          localStorage.setItem('refresh_token', response.refresh_token);

          set({
            user: response.user,
            isAuthenticated: true,
            isLoading: false,
            error: null,
          });

          return true;
        } catch (error: unknown) {
          const message =
            error instanceof Error
              ? error.message
              : 'Login failed. Please check your credentials.';

          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
            error: message,
          });

          return false;
        }
      },

      logout: () => {
        authApi.logout();
        set({
          user: null,
          isAuthenticated: false,
          error: null,
        });
      },

      checkAuth: async () => {
        const token = localStorage.getItem('access_token');

        if (!token) {
          set({ isAuthenticated: false, user: null });
          return;
        }

        // If already authenticated, don't re-check
        if (get().isAuthenticated && get().user) {
          return;
        }

        set({ isLoading: true });

        try {
          const user = await authApi.me();
          set({
            user,
            isAuthenticated: true,
            isLoading: false,
          });
        } catch {
          // Token invalid or expired
          authApi.logout();
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        }
      },

      clearError: () => {
        set({ error: null });
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
